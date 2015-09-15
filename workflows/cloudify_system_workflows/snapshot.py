########
# Copyright (c) 2015 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.


import json
import tempfile
import shutil
import zipfile
import itertools
import os
import subprocess

import elasticsearch
import elasticsearch.helpers

from cloudify.decorators import workflow
from cloudify.exceptions import NonRecoverableError
from cloudify.manager import get_rest_client
from cloudify_system_workflows.deployment_environment import \
    generate_create_dep_tasks_graph


_VERSION = '3.3'
_VERSION_FILE = 'version'
_AGENTS_FILE = 'agents.json'
_ELASTICSEARCH = 'es_data'
_CRED_DIR = 'credentials'
_CRED_KEY_NAME = 'agent_key'
_INFLUXDB = 'influxdb_data'
_INFLUXDB_DUMP_CMD = ('curl -s -G "http://localhost:8086/db/cloudify/series'
                      '?u=root&p=root&chunked=true" --data-urlencode'
                      ' "q=select * from /.*/" > {0}')
_INFLUXDB_RESTORE_CMD = ('cat {0} | while read -r line; do curl -X POST '
                         '-d "[${{line}}]" "http://localhost:8086/db/cloudify/'
                         'series?u=root&p=root" ;done')


class _DictToAttributes(object):
    def __init__(self, dic):
        self._dict = dic

    def __getattr__(self, name):
        return self._dict[name]


def _get_json_objects(f):
    def chunks(g):
        ch = g.read(10000)
        yield ch
        while ch:
            ch = g.read(10000)
            yield ch

    s = ''
    n = 0
    decoder = json.JSONDecoder()
    for ch in chunks(f):
        s += ch
        try:
            while s:
                obj, idx = decoder.raw_decode(s)
                n += 1
                yield json.dumps(obj)
                s = s[idx:]
        except:
            pass

    assert not n or not s


def _copy_data(archive_root, config, to_archive=True):
    DATA_TO_COPY = [
        (config.file_server_blueprints_folder, 'blueprints'),
        (config.file_server_uploaded_blueprints_folder, 'uploaded-blueprints')
    ]

    # files with constant relative/absolute paths
    for (p1, p2) in DATA_TO_COPY:
        if p1[0] != '/':
            p1 = os.path.join(config.file_server_root, p1)
        if p2[0] != '/':
            p2 = os.path.join(archive_root, p2)
        if not to_archive:
            p1, p2 = p2, p1

        if not os.path.exists(p1):
            continue

        if os.path.isfile(p1):
            shutil.copy(p1, p2)
        else:
            if os.path.exists(p2):
                shutil.rmtree(p2, ignore_errors=True)
            shutil.copytree(p1, p2)


def _create_es_client(config):
    return elasticsearch.Elasticsearch(hosts=[{'host': config.db_address,
                                               'port': config.db_port}])


def _except_types(s, *args):
    return (e for e in s if e['_type'] not in args)


def _clean_up_db_before_restore(es_client, wf_exec_id):
    s = elasticsearch.helpers.scan(es_client)
    for doc in _except_types(s, 'provider_context', 'snapshot'):
        if doc['_id'] != wf_exec_id:
            doc['_op_type'] = 'delete'
            yield doc


def _create(ctx, snapshot_id, config, include_metrics, include_credentials,
            **kw):
    tempdir = tempfile.mkdtemp('-snapshot-data')

    snapshots_dir = os.path.join(
        config.file_server_root,
        config.file_server_snapshots_folder
    )

    if not os.path.exists(snapshots_dir):
        os.makedirs(snapshots_dir)

    # files/dirs copy
    _copy_data(tempdir, config)

    # elasticsearch
    es = _create_es_client(config)
    _dump_elasticsearch(tempdir, es)

    # influxdb
    if include_metrics:
        _dump_influxdb(tempdir)

    # credentials
    if include_credentials:
        _dump_credentials(tempdir, es)

    # version
    with open(os.path.join(tempdir, _VERSION_FILE), 'w') as f:
        f.write(_VERSION)

    # zip
    snapshot_dir = os.path.join(snapshots_dir, snapshot_id)
    os.makedirs(snapshot_dir)

    shutil.make_archive(
        os.path.join(snapshot_dir, snapshot_id),
        'zip',
        tempdir
    )

    # end
    shutil.rmtree(tempdir)


@workflow(system_wide=True)
def create(ctx, snapshot_id, config, **kwargs):
    update_status = get_rest_client().snapshots.update_status
    config = _DictToAttributes(config)
    try:
        _create(ctx, snapshot_id, config, **kwargs)
        update_status(snapshot_id, config.created_status)
    except BaseException, e:
        update_status(snapshot_id, config.failed_status, str(e))
        raise


def _dump_elasticsearch(tempdir, es):
    storage_scan = elasticsearch.helpers.scan(es, index='cloudify_storage')
    storage_scan = _except_types(storage_scan,
                                 'provider_context',
                                 'snapshot')
    event_scan = elasticsearch.helpers.scan(es, index='cloudify_events')

    with open(os.path.join(tempdir, _ELASTICSEARCH), 'w') as f:
        for item in itertools.chain(storage_scan, event_scan):
            f.write(json.dumps(item) + '\n')


def _dump_influxdb(tempdir):
    influxdb_file = os.path.join(tempdir, _INFLUXDB)
    influxdb_temp_file = influxdb_file + '.temp'
    subprocess.call(_INFLUXDB_DUMP_CMD.format(influxdb_temp_file), shell=True)
    with open(influxdb_temp_file, 'r') as f, open(influxdb_file, 'w') as g:
        for obj in _get_json_objects(f):
            g.write(obj + '\n')

    os.remove(influxdb_temp_file)


def _dump_credentials(tempdir, es):
    archive_cred_path = os.path.join(tempdir, _CRED_DIR)
    os.makedirs(archive_cred_path)

    node_scan = elasticsearch.helpers.scan(es, index='cloudify_storage',
                                           doc_type='node')
    for n in node_scan:
        props = n['_source']['properties']
        if 'cloudify_agent' in props and 'key' in props['cloudify_agent']:
            node_id = n['_id']
            agent_key_path = props['cloudify_agent']['key']
            os.makedirs(os.path.join(archive_cred_path, node_id))
            shutil.copy(os.path.expanduser(agent_key_path),
                        os.path.join(archive_cred_path, node_id,
                                     _CRED_KEY_NAME))


def _update_es_node(es_node):
    if es_node['_type'] == 'deployment':
        workflows = es_node['_source']['workflows']
        if 'install_new_agents' not in workflows:
            workflows['install_new_agents'] = {
                'operation': 'cloudify.plugins.workflows.install_new_agents',
                'parameters': {
                    'install_agent_timeout': {
                        'default': 300
                    },
                    'node_ids': {
                        'default': []
                    },
                    'node_instance_ids': {
                        'default': []
                    }
                },
                'plugin': 'default_workflows'
            }
    if es_node['_type'] == 'node':
        source = es_node['_source']
        type_hierarchy = source.get('type_hierarchy', [])
        if 'cloudify.nodes.Compute' in type_hierarchy:
            operations = source['operations']
            op_name = 'cloudify.interfaces.cloudify_agent.create_amqp'
            if op_name not in operations:
                operations[op_name] = {
                    'inputs': {
                        'install_agent_timeout': 300
                    },
                    'has_intrinsic_functions': False,
                    'plugin': 'agent',
                    'retry_interval': None,
                    'max_retries': None,
                    'executor': 'central_deployment_agent',
                    'operation': 'cloudify_agent.operations.create_agent_amqp'
                }


def _restore_elasticsearch(ctx, tempdir, es):
    ctx.send_event('Deleting all ElasticSearch data')
    elasticsearch.helpers.bulk(
        es,
        _clean_up_db_before_restore(es, ctx.execution_id))
    es.indices.flush()

    def es_data_itr():
        for line in open(os.path.join(tempdir, _ELASTICSEARCH), 'r'):
            elem = json.loads(line)
            _update_es_node(elem)
            yield elem

    ctx.send_event('Restoring ElasticSearch data')
    elasticsearch.helpers.bulk(es, es_data_itr())
    es.indices.flush()


def _restore_influxdb_3_3(ctx, tempdir):
    ctx.send_event('Restoring InfluxDB metrics')
    influxdb_f = os.path.join(tempdir, _INFLUXDB)
    if os.path.exists(influxdb_f):
        subprocess.call(_INFLUXDB_RESTORE_CMD.format(influxdb_f), shell=True)


def _restore_credentials_3_3(ctx, tempdir, file_server_root, es):
    ctx.send_event('Restoring credentials')
    archive_cred_path = os.path.join(tempdir, _CRED_DIR)
    cred_path = os.path.join(file_server_root, _CRED_DIR)

    # in case when this is not first restore action
    if os.path.exists(cred_path):
        shutil.rmtree(cred_path)

    os.makedirs(cred_path)

    update_actions = []
    if os.path.exists(archive_cred_path):
        for node_id in os.listdir(archive_cred_path):
            os.makedirs(os.path.join(cred_path, node_id))
            agent_key_path = os.path.join(cred_path, node_id, _CRED_KEY_NAME)
            shutil.copy(os.path.join(archive_cred_path, node_id,
                        _CRED_KEY_NAME), agent_key_path)

            update_action = {
                '_op_type': 'update',
                '_index': 'cloudify_storage',
                '_type': 'node',
                '_id': node_id,
                'doc': {
                    'properties': {
                        'cloudify_agent': {
                            'key': agent_key_path
                        }
                    }
                }
            }

            update_actions.append(update_action)

    elasticsearch.helpers.bulk(es, update_actions)


def _restore_snapshot(ctx, config, tempdir):
    # files/dirs copy
    _copy_data(tempdir, config, to_archive=False)

    # elasticsearch
    es = _create_es_client(config)
    _restore_elasticsearch(ctx, tempdir, es)

    # influxdb
    _restore_influxdb_3_3(ctx, tempdir)

    # credentials
    _restore_credentials_3_3(ctx, tempdir, config.file_server_root, es)

    es.indices.flush()
    # end


def _restore_snapshot_format_3_3(ctx, config, tempdir):
    _restore_snapshot(ctx, config, tempdir)


# In 3.3 cloudify_agent dict was added to node instances runtime properties.
# This code is used to fill those dicts when migrating from 3.2.
def insert_agents_data(client, agents):
    for nodes in agents.values():
        for node_instances in nodes.values():
            for node_instance_id, agent in node_instances.iteritems():
                node_instance = client.node_instances.get(node_instance_id)
                runtime_properties = node_instance.runtime_properties
                runtime_properties['cloudify_agent'] = agent
                client.node_instances.update(
                    node_instance_id=node_instance_id,
                    runtime_properties=runtime_properties)


def _restore_snapshot_format_3_2(ctx, config, tempdir):
    _restore_snapshot(ctx, config, tempdir)
    ctx.send_event('Updating cloudify agent data')
    client = get_rest_client()
    with open(os.path.join(tempdir, _AGENTS_FILE)) as agents_file:
        agents = json.load(agents_file)
    insert_agents_data(client, agents)


@workflow(system_wide=True)
def restore(ctx, snapshot_id, config, **kwargs):
    mappings = {
        '3.3': _restore_snapshot_format_3_3,
        '3.2': _restore_snapshot_format_3_2
    }

    config = _DictToAttributes(config)
    tempdir = tempfile.mkdtemp('-snapshot-data')

    try:
        file_server_root = config.file_server_root
        snapshots_dir = os.path.join(
            file_server_root,
            config.file_server_snapshots_folder
        )

        snapshot_path = os.path.join(snapshots_dir, snapshot_id, '{0}.zip'
                                     .format(snapshot_id))

        with zipfile.ZipFile(snapshot_path, 'r') as zipf:
            zipf.extractall(tempdir)

        with open(os.path.join(tempdir, _VERSION_FILE), 'r') as f:
            from_version = f.read()

        if from_version not in mappings:
            raise NonRecoverableError('Manager is not able to restore snapshot'
                                      ' of manager {0}'.format(from_version))

        ctx.send_event('Starting restoring snapshot of manager {0}'
                       .format(from_version))
        mappings[from_version](ctx, config, tempdir)

        ctx.load_deployments_contexts()
        rest_client = get_rest_client()
        for dep_id, dep_ctx in ctx.deployments_contexts.iteritems():
            dep = rest_client.deployments.get(dep_id)
            blueprint = rest_client.blueprints.get(dep_ctx.blueprint.id)
            blueprint_plan = blueprint['plan']
            tasks_graph = generate_create_dep_tasks_graph(
                dep_ctx,
                deployment_plugins_to_install=blueprint_plan[
                    'deployment_plugins_to_install'],
                workflow_plugins_to_install=blueprint_plan[
                    'workflow_plugins_to_install'],
                policy_configuration={
                    'policy_types': dep['policy_types'],
                    'policy_triggers': dep['policy_triggers'],
                    'groups': dep['groups']
                }
            )
            try:
                dep_ctx.internal.start_local_tasks_processing()
                dep_ctx.internal.start_event_monitor()
                tasks_graph.execute()
            finally:
                dep_ctx.internal.stop_local_tasks_processing()
                dep_ctx.internal.stop_event_monitor()
            ctx.send_event('Successfully created {0}\'s deployment environment'
                           .format(dep_id))
        ctx.send_event('Successfully restored snapshot of manager {0}'
                       .format(from_version))
    finally:
        shutil.rmtree(tempdir)
