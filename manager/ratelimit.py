import time
from tinydb import TinyDB, Query
from tinydb.operations import increment
from tinydb.table import Document


class RateLimitManager:
    """Quota manager"""

    def __init__(self):
        self.limit_db = TinyDB("data/rate_limit.json")
        self.usage_db = TinyDB("data/rate_usage.json")
        self.draw_limit_db = TinyDB("data/draw_rate_limit.json")
        self.draw_usage_db = TinyDB("data/draw_rate_usage.json")

    def update(self, _type: str, _id: str, rate: int):
        """Update quota limit"""

        q = Query()
        self.limit_db.upsert({"type": _type, "id": _id, "rate": rate}, q.fragment({"type": _type, "id": _id}))

    def update_draw(self, _type: str, _id: str, rate: int):
        """Update drawing quota limit"""

        q = Query()
        self.draw_limit_db.upsert({"type": _type, "id": _id, "rate": rate}, q.fragment({"type": _type, "id": _id}))

    def list(self):
        """List all quota limits"""

        return self.limit_db.all()

    def get_limit(self, _type: str, _id: str) -> Document:
        """Get restrictions"""

        q = Query()
        entity = self.limit_db.get(q.fragment({"type": _type, "id": _id}))
        if entity is None and _id != 'default':
            return self.limit_db.get(q.fragment({"type": _type, "id": 'default'}))
        return entity

    def get_draw_limit(self, _type: str, _id: str) -> Document:
        """Get drawing limits"""

        q = Query()
        entity = self.draw_limit_db.get(q.fragment({"type": _type, "id": _id}))
        if entity is None and _id != 'default':
            return self.draw_limit_db.get(q.fragment({"type": _type, "id": 'default'}))
        return entity

    def get_draw_usage(self, _type: str, _id: str) -> Document:
        """Get drawing usage"""

        q = Query()
        usage = self.draw_usage_db.get(q.fragment({"type": _type, "id": _id}))
        current_time = time.localtime(time.time()).tm_hour
        current_day = time.localtime(time.time()).tm_mday

        # Delete expired records
        if usage is not None and usage['time'] != current_time:
            self.draw_usage_db.remove(doc_ids=[usage.doc_id])
            usage = None

        # initialization
        if usage is None:
            usage = {'type': _type, 'id': _id, 'count': 0, 'time': current_time, 'day': current_day}
            self.draw_usage_db.insert(usage)

        return usage

    def get_usage(self, _type: str, _id: str) -> Document:
        """Get usage"""

        q = Query()
        usage = self.usage_db.get(q.fragment({"type": _type, "id": _id}))
        current_time = time.localtime(time.time()).tm_hour
        current_day = time.localtime(time.time()).tm_mday

        # Delete expired records
        time_diff_dondition = (usage is not None and usage['time'] != current_time)
        day_diff_condition = (usage is not None and usage['time'] == current_time and usage['day'] != current_day)
        if time_diff_dondition or day_diff_condition:
            self.usage_db.remove(doc_ids=[usage.doc_id])
            usage = None
            
        # initialization
        if usage is None:
            usage = {'type': _type, 'id': _id, 'count': 0, 'time': current_time, 'day': current_day}
            self.usage_db.insert(usage)

        return usage

    def increment_usage(self, _type, _id):
        """Update usage"""

        self.get_usage(_type, _id)

        q = Query()
        self.usage_db.update(increment('count'), q.fragment({"type": _type, "id": _id}))

    def increment_draw_usage(self, _type, _id):
        """Update drawing usage"""

        self.get_usage(_type, _id)

        q = Query()
        self.draw_usage_db.update(increment('count'), q.fragment({"type": _type, "id": _id}))

    def check_exceed(self, _type: str, _id: str) -> float:
        """Check whether the quota is exceeded and return the usage/quota"""

        limit = self.get_limit(_type, _id)
        usage = self.get_usage(_type, _id)

        # No restrictions under this type
        if limit is None:
            return 0

        # This type is prohibited
        return 1 if limit['rate'] == 0 else usage['count'] / limit['rate']

    def check_draw_exceed(self, _type: str, _id: str) -> float:
        """Check whether the drawing exceeds the quota and return the usage/amount"""

        limit = self.get_draw_limit(_type, _id)
        usage = self.get_draw_usage(_type, _id)

        # No restrictions under this type
        if limit is None:
            return 0

        # This type is prohibited
        return 1 if limit['rate'] == 0 else usage['count'] / limit['rate']