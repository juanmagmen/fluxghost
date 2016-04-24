
from glob import glob
import logging
import json
import sys

from serial.tools import list_ports as _list_ports
from fluxclient.encryptor import KeyObject
# from fluxclient.upnp import UpnpDiscover
from fluxclient.upnp.task import UpnpTask
from .base import WebSocketBase, WebsocketBinaryHelperMixin, BinaryUploadHelper, SIMULATE, OnTextMessageMixin

logger = logging.getLogger(__name__)


def check_task(func):
    def f(self, *args, **kwargs):
        if self.upnp_task:
            return func(self, *args, **kwargs)
        else:
            self.send_errer('Not connected')
            return
    return f


class WebsocketUpnp(OnTextMessageMixin, WebsocketBinaryHelperMixin, WebSocketBase):

    def __init__(self, *args, **kw):
        super(WebsocketUsbConfig, self).__init__(*args, **kw)

        self.client_key = None
        self.password = None
        self.upnp_task = None
        self.cmd_mapping = {
            'connect': [self.connect],
            'scan_wifi': [self.scan_wifi],
            'upload_key': [self.upload_key],
            'upload_password': [self.upload_password],
            'add_key': [self.add_key],
            'config_network': [self.config_network]
        }

    def upload_key(self, params):
        pem = params
        self.client_key = KeyObject.load_keyobj(pem)
        self.send_json(status="ok")

    def upload_password(self, params):
        self.password = params.strip()
        self.send_json(status="ok")

    def connect(self, params):
        self.close_task()
        uuid, params = params.split(None, 1)

        params = json.loads(params)
        # uuid, client_key, ipaddr=None, device_metadata=None,
        #          remote_profile=None, backend_options={}, lookup_callback=None,
        #          lookup_timeout=float("INF")
        valid_patams = {'client_key': self.client_key, 'uuid': uuid}
        for i in ['ipaddr', 'device_metadata', 'remote_profile', 'backend_options', 'lookup_callback', 'lookup_timeout']:
            if i in params:
                valid_patams[i] = params[i]

        if self.password:
            valid_patams['backend_options'] = valid_patams.get('backend_options', {})
            valid_patams['backend_options']['password'] = self.password

        if 'uuid' in valid_patams and valid_patams[client_key]:
            self.upnp_task = UpnpTask(**valid_patams)
            self.send_ok()
        else:
            self.send_fatal('api fail')
            print('valid_patams', valid_patams)

    @check_task
    def scan_wifi(self, params):
        self.send_json(status="ok", wifi=self.upnp_task.get_wifi_list())

    @check_task
    def add_key(self, params):
        self.upnp_task.add_trust()

    @check_task
    def config_network(self, params):
        options = json.loads(params)
        self.task.config_network(options)
        self.send_text('{"status": "ok"}')

    # def auth(self, password=None):
    #     if password:
    #         self.task.auth(password)
    #     else:
    #         self.task.auth()
    #     self.send_text('{"status": "ok", "cmd": "auth"}')

    # def config_general(self, params):
    #     options = json.loads(params)
    #     self.task.config_general(options)
    #     self.send_text('{"status": "ok"}')

    # def scan_wifi(self):
    #     ret = self.task.list_ssid()
    #     self.send_json(status="ok", cmd="scan", wifi=ret)

    # def get_network(self):
    #     payload = {"status": "ok", "cmd": "network"}
    #     payload["ssid"] = self.task.get_ssid()
    #     payload["ipaddr"] = self.task.get_ipaddr()
    #     self.send_json(payload)

    # def set_password(self, password):
    #     ret = self.task.set_password(password)
    #     if ret == "OK":
    #         self.send_text('{"status": "ok", "cmd": "password"}')
    #     else:
    #         self.send_error(ret)

    # def on_binary_message(self, buf):
    #     pass
    def on_close(self, message):
        self.close_task()

    def close_task(self):
        if self.upnp_task:
            self.upnp_task.close()
            self.upnp_task = None
