from cloudify import ctx
from configobj import ConfigObj
from cloudify.state import ctx_parameters as inputs
import os


targetInstance = ctx.target.instance
srcInstance = ctx.source.instance

diamond_paths = srcInstance.runtime_properties['diamond_paths']
config_full_path = os.path.join(
    diamond_paths['collectors_config'],
    'SNMPProxyCollector.conf'
)

config = ConfigObj(infile=config_full_path, raise_errors=True)

devicesConf = config.get('devices', {})
devicesConf[ctx.target.node.name] = device_config = {}
device_config['instance_id'] = targetInstance.id
if 'host' in inputs:
    device_config['host'] = inputs.host
else:
    device_config['host'] = targetInstance.host_ip
device_config['port'] = inputs.port
device_config['community'] = inputs.community
device_config['oids'] = inputs.oids
config['devices'] = devicesConf
config.write()

srcInstance._node._get_node_if_needed()
