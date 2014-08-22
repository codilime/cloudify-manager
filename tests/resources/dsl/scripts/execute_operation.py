from cloudify.workflows import ctx
from cloudify.workflows import parameters as p


node_instance = list(ctx.get_node(p.node_id).instances)[0]
node_instance.execute_operation(
    operation=p.operation,
    kwargs=p.properties).get()
