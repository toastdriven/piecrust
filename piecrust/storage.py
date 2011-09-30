class BaseStorage(object):
    # Read-only (NECESSARY) methods.
    def all_objects(self, request):
        raise NotImplementedError()

    def list(self, **kwargs):
        raise NotImplementedError()

    def single(self, **kwargs):
        raise NotImplementedError()

    # Methods needed for write-access.
    def create(self, **kwargs):
        raise NotImplementedError()

    def update(self, **kwargs):
        raise NotImplementedError()

    def delete_list(self, **kwargs):
        raise NotImplementedError()

    def delete_single(self, **kwargs):
        raise NotImplementedError()

    def rollback(self, bundles):
        raise NotImplementedError()
