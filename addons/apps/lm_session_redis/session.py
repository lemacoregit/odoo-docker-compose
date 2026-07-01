# Copyright 2016-2024 Lema Core Technologies (http://www.lemacore.com)
# License OPL-3 or later (http://www.gnu.org/licenses/agpl.html)

import base64
import json
import logging
import os
import re
import time
from hashlib import sha512

from odoo.http import SESSION_DELETION_TIMER, STORED_SESSION_BYTES
from odoo.service import security
from odoo.tools._vendor.sessions import SessionStore

from . import json_encoding

# Odoo 19's session-id contract (base64 urlsafe, 84 chars, first
# STORED_SESSION_BYTES used as a stable prefix for soft rotation and CSRF
# token computation). The base SessionStore this class inherits from still
# generates 40-char hex/SHA1 keys, which is the pre-Odoo-19 format and is
# incompatible with soft rotation's prefix slicing — so both key generation
# and validation must be overridden to match core.
_base64_urlsafe_re = re.compile(r"^[A-Za-z0-9_-]{84}$")

# this is equal to the duration of the session garbage collector in
# odoo.http.session_gc()
DEFAULT_SESSION_TIMEOUT = 60 * 60 * 24 * 7  # 7 days in seconds
DEFAULT_SESSION_TIMEOUT_ANONYMOUS = 60 * 60 * 3  # 3 hours in seconds

_logger = logging.getLogger(__name__)


class RedisSessionStore(SessionStore):
    """SessionStore that saves session to redis"""

    def __init__(
        self,
        redis,
        session_class=None,
        prefix="",
        expiration=None,
        anon_expiration=None,
    ):
        super().__init__(session_class=session_class)
        self.redis = redis
        if expiration is None:
            self.expiration = DEFAULT_SESSION_TIMEOUT
        else:
            self.expiration = expiration
        if anon_expiration is None:
            self.anon_expiration = DEFAULT_SESSION_TIMEOUT_ANONYMOUS
        else:
            self.anon_expiration = anon_expiration
        self.prefix = "session:"
        if prefix:
            self.prefix = f"{self.prefix}:{prefix}:"

    def build_key(self, sid):
        return f"{self.prefix}{sid}"

    def generate_key(self, salt=None):
        # Same scheme as Odoo 19's FilesystemSessionStore.generate_key(),
        # required so STORED_SESSION_BYTES prefix slicing in rotate() below
        # lines up with what core expects.
        key = str(time.time()).encode() + os.urandom(64)
        hash_key = sha512(key).digest()[:-1]  # prevent base64 padding
        return base64.urlsafe_b64encode(hash_key).decode("utf-8")

    def is_valid_key(self, key):
        return _base64_urlsafe_re.match(key) is not None

    def save(self, session):
        key = self.build_key(session.sid)

        # Odoo's Session class uses __slots__ without an `expiration`
        # attribute (Odoo 19+), so per-session overrides are not possible.
        if session.uid:
            expiration = self.expiration
        else:
            expiration = self.anon_expiration
        if _logger.isEnabledFor(logging.DEBUG):
            if session.uid:
                user_msg = f"user '{session.login}' (id: {session.uid})"
            else:
                user_msg = "anonymous user"
            _logger.debug(
                f"saving session with key '{key}' and "
                f"expiration of {expiration} seconds for {user_msg}"
            )

        data = json.dumps(dict(session), cls=json_encoding.SessionEncoder).encode(
            "utf-8"
        )
        if self.redis.set(key, data):
            return self.redis.expire(key, expiration)

    def delete(self, session):
        key = self.build_key(session.sid)
        _logger.debug(f"deleting session with key {key}")
        return self.redis.delete(key)

    def delete_old_sessions(self, session):
        """Finalize a pending soft-rotation: once the grace period for the
        previous sid has elapsed, drop the `gc_previous_sessions` marker.
        The previous sid's Redis key is left alone — its own TTL (set in
        save()) already expires it, so there is nothing to delete here."""
        if "gc_previous_sessions" in session:
            if session["create_time"] + SESSION_DELETION_TIMER < time.time():
                del session["gc_previous_sessions"]
                self.save(session)

    def get(self, sid):
        if not self.is_valid_key(sid):
            _logger.debug(
                f"session with invalid sid '{sid}' has been asked, "
                "returning a new one"
            )
            return self.new()

        key = self.build_key(sid)
        saved = self.redis.get(key)
        if not saved:
            _logger.debug(
                f"session with non-existent key '{key}' has been asked, "
                "returning a new one"
            )
            return self.new()
        try:
            data = json.loads(saved.decode("utf-8"), cls=json_encoding.SessionDecoder)
        except ValueError:
            _logger.debug(
                f"session for key '{key}' has been asked but its json "
                "content could not be read, it has been reset"
            )
            data = {}
        return self.session_class(data, sid, False)

    def list(self):
        keys = self.redis.keys("%s*" % self.prefix)
        _logger.debug("a listing redis keys has been called")
        return [
            (key.decode("utf-8") if isinstance(key, bytes) else key)[
                len(self.prefix) :
            ]
            for key in keys
        ]

    def rotate(self, session, env, soft=False):
        # Mirrors FilesystemSessionStore.rotate(): a soft rotation keeps the
        # first half of the sid stable for a short grace period so
        # concurrent in-flight requests using the old sid remain valid,
        # while a hard rotation invalidates the old sid immediately.
        if soft:
            static = session.sid[:STORED_SESSION_BYTES]
            recent_session = self.get(session.sid)
            if "next_sid" in recent_session:
                # A concurrent request already rotated this session.
                session.sid = recent_session["next_sid"]
                return
            next_sid = static + self.generate_key()[STORED_SESSION_BYTES:]
            session["next_sid"] = next_sid
            session["deletion_time"] = time.time() + SESSION_DELETION_TIMER
            self.save(session)
            # Now prepare the new session.
            session["gc_previous_sessions"] = True
            session.sid = next_sid
            del session["deletion_time"]
            del session["next_sid"]
        else:
            self.delete(session)
            session.sid = self.generate_key()
        if session.uid:
            assert env, "saving this session requires an environment"
            session.session_token = security.compute_session_token(session, env)
        session.should_rotate = False
        session["create_time"] = time.time()
        self.save(session)

    def vacuum(self, *args, **kwargs):
        """Do not garbage collect the sessions

        Redis keys are automatically cleaned at the end of their
        expiration.
        """
        return None
