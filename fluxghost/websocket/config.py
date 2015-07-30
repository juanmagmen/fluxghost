import logging
import platform
import dbm
from os.path import expanduser


from .base import WebSocketBase

logger = logging.getLogger("WS.CONFIG")

WRITE_OP = "w"
READ_OP = "r"


class WebsocketConfig(WebSocketBase):
    operation = None
    config_path = ''
    config_file = 'FluxStudio'  # TODO: find a proper name~

    if platform.platform().startswith("Darwin"):
        config_path = expanduser("~") + '/Library/Preferences/'
    elif platform.platform().startswith("Linux"):
        config_path = expanduser("~") + '/.'
    else:
        # c:\Users\John\.
        raise RuntimeError("Unknow platform!!")

    logger.debug('will store in %s' % (config_path + config_file))

    def on_close(self, *args, **kw):
        super(WebsocketConfig, self).on_close(*args, **kw)

        try:
            self.db.close()
        except:
            pass

    def on_text_message(self, message):
        op, self.key = message.split(" ", 1)

        try:
            if self.operation:
                raise RuntimeError("CONFIG_FILE_ALREADY_OPENED")

            if op == WRITE_OP:
                self.operation = WRITE_OP
                self.db = dbm.open(self.config_path + self.config_file, 'c')
                self.send('{"status": "opened"}')

            elif op == READ_OP:
                self.operation = READ_OP
                self.db = dbm.open(self.config_path + self.config_file, 'c')
                self.send('{"status": "opened"}')
                self.read_key()

            else:
                raise RuntimeError("BAD_FILE_OPERATION")

        except RuntimeError as e:
            self.send("error %s" % e.args[0])
            self.close()

        # NO NEED
        # except FileNotFoundError:
        #     self.send("error FILE_NOT_EXIST")
        #     self.close()

        except PermissionError:
            self.send("error ACCESS_DENY")
            self.close()
        except Exception as e:
            self.send("error UNKNOW_ERROR %s" % e)
            self.close()

    def on_binary_message(self, buf):
        if self.operation == WRITE_OP:
            self.db[key] = buf

    def read_key(self):
        self.send_binary(self.db[key])
