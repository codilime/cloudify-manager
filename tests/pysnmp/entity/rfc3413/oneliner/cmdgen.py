class ObjectName(object):

    def __init__(self, oid):
        self.oid = oid  # tuple like (1, 3, 6, 1, 4, 1, 2021, 10, 1, 3, 3)

    def prettyPrint(self):
        return ".".join(map(lambda d: str(d), self.oid))


class OctetString(object):

    def __init__(self, x):
        self.x = x

    def prettyPrint(self):
        return str(self.x)


class CommandGenerator(object):

    def __init__(self, *args, **kwargs):
        pass

    def getCmd(self, snmpAuthData, snmpTransportData, oid):
        return (None, None, None, [(ObjectName(oid), OctetString(0.9))])


class CommunityData(object):

    def __init__(self, *args, **kwargs):
        pass


class UdpTransportTarget(object):

    def __init__(self, *args, **kwargs):
        pass
