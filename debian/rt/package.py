class BasePackage(object):
    def __init__(self, **kwargs):
        for key in kwargs:
            setattr(self, key, kwargs[key])


class SourcePackage(BasePackage):
    pass


class BinaryPackage(BasePackage):
    pass

