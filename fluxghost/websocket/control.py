
from errno import EPIPE, EHOSTDOWN, errorcode
from uuid import UUID
import logging
import socket
import shlex

from io import BytesIO

from fluxclient.encryptor import KeyObject
from fluxclient.utils.version import StrictVersion
from fluxclient.fcode.g_to_f import GcodeToFcode
from fluxclient.robot.errors import RobotError, RobotSessionError
from .base import WebSocketBase

logger = logging.getLogger("WS.CONTROL")


"""
Control printer

Javascript Example:

ws = new WebSocket("ws://localhost:8000/ws/control/RLFPAPI7E8KXG64KG5NOWWY3T");
ws.onmessage = function(v) { console.log(v.data);}
ws.onclose = function(v) { console.log("CONNECTION CLOSED, code=" + v.code +
    "; reason=" + v.reason); }

// After recive connected...
ws.send("ls")
"""


STAGE_DISCOVER = '{"status": "connecting", "stage": "discover"}'
STAGE_ROBOT_CONNECTING = '{"status": "connecting", "stage": "connecting"}'
STAGE_CONNECTED = '{"status": "connected"}'
STAGE_TIMEOUT = '{"status": "error", "error": "TIMEOUT"}'


class WebsocketControlBase(WebSocketBase):
    binary_handler = None
    cmd_mapping = None
    client_key = None
    robot = None

    def __init__(self, request, client, server, path, serial):
        WebSocketBase.__init__(self, request, client, server, path)
        self.uuid = UUID(hex=serial)
        self.POOL_TIME = 1.5

    def on_connected(self):
        pass

    def on_loop(self):
        if self.client_key and not self.robot:
            self.try_connect()

    def get_robot_from_device(self, device):
        return device.connect_robot(
            self.client_key, conn_callback=self._conn_callback)

    def try_connect(self):
        self.send_text(STAGE_DISCOVER)
        logger.debug("DISCOVER")
        uuid = self.uuid

        if uuid in self.server.discover_devices:
            device = self.server.discover_devices[uuid]
            self.remote_version = device.version
            self.ipaddr = device.ipaddr

            try:
                self.send_text(STAGE_ROBOT_CONNECTING)
                self.robot = self.get_robot_from_device(device)

            except OSError as err:
                error_no = err.args[0]
                if error_no == EHOSTDOWN:
                    self.send_fatal("DISCONNECTED")
                else:
                    self.send_fatal("UNKNOWN_ERROR",
                                    errorcode.get(error_no, error_no))
                return

            except (RobotError, RobotSessionError) as err:
                if err.args[0] == "REMOTE_IDENTIFY_ERROR":
                    mk = device.master_key
                    sk = device.slave_key
                    ms = mk.public_key_pem if mk else "N/A"
                    ss = sk.public_key_pem if sk else "N/A"
                    logger.error("RIE\nMasterKey:\n%s\nSlaveKey:\n%s",
                                 ms.decode(), ss.decode())
                    self.server.discover_devices.pop(uuid)
                self.send_fatal(*err.error_symbol)
                return

            self.send_text(STAGE_CONNECTED)
            self.POOL_TIME = 30.0
            self.on_connected()

    def on_text_message(self, message):
        if self.client_key:
            self.on_command(message)
        else:
            try:
                self.client_key = KeyObject.load_keyobj(message)
            except Exception:
                logger.error("RSA Key load error: %s", message)
                self.send_fatal("BAD_PARAMS")
                raise

            self.try_connect()

    def on_binary_message(self, buf):
        if self.binary_handler:
            self.binary_handler(buf)
        else:
            self.send_fatal("PROTOCOL_ERROR", "Can not accept binary data")

    def cb_upload_callback(self, robot, sent, size):
        self.send_json(status="uploading", sent=sent)

    def simple_binary_transfer(self, method, mimetype, size, upload_to=None,
                               cb=None):
        ref = method(mimetype, size, upload_to)

        def binary_handler(buf):
            try:
                feeder = ref.__next__()
                sent = feeder(buf)
                self.send_json(status="uploading", sent=sent)
                if sent == size:
                    ref.__next__()
            except StopIteration:
                self.binary_handler = None
                cb()

        ref.__next__()
        self.binary_handler = binary_handler
        self.send_continue()

    def simple_binary_receiver(self, size, continue_cb):
        swap = BytesIO()
        upload_meta = {'sent': 0}

        def binary_handler(buf):
            swap.write(buf)
            sent = upload_meta['sent'] = upload_meta['sent'] + len(buf)

            if sent < size:
                pass
            elif sent == size:
                self.binary_handler = None
                continue_cb(swap)
            else:
                self.send_fatal("NOT_MATCH", "binary data length error")

        self.binary_handler = binary_handler
        self.send_continue()

    def _fix_auth_error(self, task):
        self.send_text(STAGE_DISCOVER)
        if task.timedelta < -15:
            logger.warn("Auth error, try fix time delta")
            old_td = task.timedelta
            task.reload_remote_profile(lookup_timeout=30.)
            if task.timedelta - old_td > 0.5:
                # Fix timedelta issue let's retry
                p = self.server.discover_devices.get(self.uuid)
                if p:
                    p["timedelta"] = task.timedelta
                    self.server.discover_devices[self.uuid] = p
                    return True
        return False

    def on_closed(self):
        if self.robot:
            self.robot.close()
            self.robot = None
        self.cmd_mapping = None

    def _disc_callback(self, *args):
        self.send_text(STAGE_DISCOVER)
        return True

    def _conn_callback(self, *args):
        self.send_text(STAGE_ROBOT_CONNECTING)
        return True


class WebsocketControl(WebsocketControlBase):
    raw_sock = None

    def __init__(self, *args, **kw):
        try:
            WebsocketControlBase.__init__(self, *args, **kw)
        except RobotError:
            pass

    # def simple_robot_invoke(func_name):
    #     def wrapper(self, *args):
    #         try:
    #             func = self.robot.__getattribute__(func_name)
    #             func(*args)
    #             self.send_ok()
    #         except RobotError as e:
    #             self.send_error(*e.args)
    #         except Exception as e:
    #             logger.exception("Unknow Error")
    #             self.send_error("UNKNOW_ERROR", repr(e.__class__))
    #     return wrapper

    def on_connected(self):
        self.set_hooks()

    def set_hooks(self):
        if self.remote_version < StrictVersion("1.0b13"):
            logger.warn("Remote version is too old, allow update fw only")
            self.cmd_mapping = {
                "update_fw": self.update_fw,
            }
            return

        self.cmd_mapping = {
            # deprecated
            "ls": self.list_file,
            # deprecated
            "select": self.select_file,
            # deprecated
            "mkdir": self.mkdir,
            # deprecated
            "rmdir": self.rmdir,
            # deprecated
            "rmfile": self.rmfile,
            # deprecated
            "cpfile": self.cpfile,
            # deprecated
            "fileinfo": self.fileinfo,
            # deprecated
            "upload": self.upload_file,

            "update_fw": self.update_fw,
            "update_mbfw": self.update_mbfw,

            "report": self.report_play,
            "kick": self.kick,

            "file": {
                "ls": self.list_file,
                "mkdir": self.mkdir,
                "rmdir": self.rmdir,
                "rmfile": self.rmfile,
                "cpfile": self.cpfile,
                "info": self.fileinfo,
                "md5": self.filemd5,
                "upload": self.upload_file,
                "download": self.download,
                "download2": self.download2,
            },

            "maintain": {
                "load_filament": self.maintain_load_filament,
                "unload_filament": self.maintain_unload_filament,
                "calibrating": self.maintain_calibrating,
                "zprobe": self.maintain_zprobe,
                "headinfo": self.maintain_headinfo,
                "headstatus": self.maintain_headstatus,
                "home": self.maintain_home,
                "update_hbfw": self.maintain_update_hbfw
            },

            "config": {
                "set": self.config_set,
                "get": self.config_get,
                "del": self.config_del
            },

            "play": {
                "select": self.select_file,
                "start": self.start_play,
                "info": self.play_info,
                "report": self.report_play,
                "pause": self.pause_play,
                "resume": self.resume_play,
                "abort": self.abort_play,
                "quit": self.quit_play
            },

            "scan": {
                "oneshot": self.scan_oneshot,
                "scanimages": self.scanimages,
                "backward": self.scan_backward,
                "forward": self.scan_forward,
                "step": self.scan_step,
            },

            "task": {
                "maintain": self.task_begin_maintain,
                "scan": self.task_begin_scan,
                "raw": self.task_begin_raw,
                "quit": self.task_quit,
            }
        }

    def invoke_command(self, ref, args, wrapper=None):
        if not args:
            return False

        cmd = args[0]
        if cmd in ref:
            obj = ref[cmd]
            if isinstance(obj, dict):
                return self.invoke_command(obj, args[1:], wrapper)
            else:
                if wrapper:
                    wrapper(obj, *args[1:])
                else:
                    obj(*args[1:])
                return True
        return False

    def on_command(self, message):
        if message == "ping":
            self.send_text('{"status": "pong"}')
            return

        if self.raw_sock:
            self.on_raw_message(message)
            return

        args = shlex.split(message)

        try:
            if self.invoke_command(self.cmd_mapping, args):
                pass
            else:
                logger.warn("Unknow Command: %s" % message)
                self.send_error("UNKNOWN_COMMAND", "LEVEL: websocket")

        except RobotError as e:
            logger.debug("RobotError%s" % repr(e.args))
            self.send_error(*e.args)

        except (TimeoutError, ConnectionResetError,  # noqa
                socket.timeout, ) as e:
            from fluxclient.robot.robot import FluxRobot
            import sys
            _, _, t = sys.exc_info()
            while t.tb_next:
                t = t.tb_next
                if "self" in t.tb_frame.f_locals:
                    if isinstance(t.tb_frame.f_locals["self"], FluxRobot):
                        self.send_fatal("TIMEOUT", repr(e.args))
                        return
            self.send_error("UNKNOWN_ERROR2", repr(e.__class__))

        except socket.error as e:
            if e.args[0] == EPIPE:
                self.send_fatal("DISCONNECTED", repr(e.__class__))
            else:
                logger.exception("Unknow socket error")
                self.send_fatal("UNKNOWN_ERROR", repr(e.__class__))

        except Exception as e:
            logger.exception("Unknow error while process text")
            self.send_error("UNKNOWN_ERROR", repr(e.__class__))

    def kick(self):
        self.robot.kick()
        self.send_ok(cmd="kick")

    def list_file(self, location=""):
        if location and location != "/":
            path = location if location.startswith("/") else "/" + location
            dirs = []
            files = []
            for is_dir, name in self.robot.list_files(path):
                if is_dir:
                    dirs.append(name)
                else:
                    files.append(name)

            dirs.sort()
            files.sort()
            self.send_ok(cmd="ls", path=location, directories=dirs,
                         files=files)
        else:
            self.send_ok(cmd="ls", path=location, directories=["SD", "USB"],
                         files=[])

    def select_file(self, file):
        path = file if file.startswith("/") else "/" + file
        self.robot.select_file(path)
        self.send_ok(cmd="select", path=file)

    def fileinfo(self, file):
        path = file if file.startswith("/") else "/" + file
        info, binary = self.robot.file_info(path)
        if binary:
            # TODO
            self.send_json(status="binary", mimetype=binary[0][0],
                           size=len(binary[0][1]))
            self.send_binary(binary[0][1])

        self.send_json(status="ok", **info)

    def filemd5(self, file):
        path = file if file.startswith("/") else "/" + file
        hash = self.robot.file_md5(path)
        self.send_json(status="ok", cmd="md5", file=file, md5=hash)

    def mkdir(self, file):
        path = file if file.startswith("/") else "/" + file
        if path.startswith("/SD/"):
            self.robot.mkdir(path)
            self.send_json(status="ok", cmd="mkdir", path=file)
        else:
            self.send_text('{"status": "error", "error": "NOT_SUPPORT"}')

    def rmdir(self, file):
        path = file if file.startswith("/") else "/" + file
        if file.startswith("/SD/"):
            self.robot.rmdir(path)
            self.send_json(status="ok", cmd="rmdir", path=file)
        else:
            self.send_text('{"status": "error", "error": "NOT_SUPPORT"}')

    def rmfile(self, file):
        path = file if file.startswith("/") else "/" + file
        if file.startswith("/SD/"):
            self.robot.rmfile(path)
            self.send_json(status="ok", cmd="rmfile", path=file)
        else:
            self.send_text('{"status": "error", "error": "NOT_SUPPORT"}')

    def download(self, file):
        def report(left, size):
            self.send_json(status="continue", left=left, size=size)

        path = file if file.startswith("/") else "/" + file
        buf = BytesIO()
        mimetype = self.robot.download_file(path, buf, report)
        if mimetype:
            self.send_json(status="binary", mimetype=mimetype,
                           size=buf.truncate())
            self.send_binary(buf.getvalue())

    def download2(self, file):
        flag = []

        def report(left, size):
            if not flag:
                flag.append(1)
                self.send_json(status="transfer", completed=0, size=size)
            self.send_json(status="transfer",
                           completed=(size - left), size=size)

        path = file if file.startswith("/") else "/" + file
        buf = BytesIO()
        mimetype = self.robot.download_file(path, buf, report)
        if mimetype:
            self.send_json(status="binary", mimetype=mimetype,
                           size=buf.truncate())
            self.send_binary(buf.getvalue())
            self.send_ok()

    def cpfile(self, source, target):
        spath = source if source.startswith("/") else "/" + source
        tpath = target if target.startswith("/") else "/" + target
        self.robot.cpfile(spath, tpath)
        self.send_json(status="ok", cmd="cpfile", source=source,
                       target=target)

    def upload_file(self, mimetype, ssize, upload_to="#"):
        if upload_to == "#":
            pass
        elif not upload_to.startswith("/"):
            upload_to = "/" + upload_to

        size = int(ssize)
        if mimetype == "text/gcode":
            if upload_to.endswith('.gcode'):
                upload_to = upload_to[:-5] + 'fc'

            def upload_callback(swap):
                gcode_content = swap.getvalue().decode("ascii", "ignore")
                gcode_content = gcode_content.split('\n')

                fcode_output = BytesIO()
                g2f = GcodeToFcode()
                g2f.process(gcode_content, fcode_output)

                fcode_len = fcode_output.truncate()
                remote_sent = 0

                fcode_output.seek(0)
                sock = self.robot.begin_upload('application/fcode',
                                               fcode_len,
                                               cmd="file upload",
                                               upload_to=upload_to)
                self.send_json(status="uploading", sent=0,
                               amount=fcode_len)
                while remote_sent < fcode_len:
                    remote_sent += sock.send(fcode_output.read(4096))
                    self.send_json(status="uploading", sent=remote_sent)

                resp = self.robot.get_resp().decode("ascii", "ignore")
                if resp == "ok":
                    self.send_ok()
                else:
                    errargs = resp.split(" ")
                    self.send_error(*(errargs[1:]))

            self.simple_binary_receiver(size, upload_callback)

        elif mimetype == "application/fcode":
            self.simple_binary_transfer(
                self.robot.yihniwimda_upload_stream, mimetype, size,
                upload_to=upload_to, cb=self.send_ok)

        else:
            self.send_text('{"status":"error", "error": "FCODE_ONLY"}')
            return

    def update_fw(self, mimetype, ssize):
        size = int(ssize)

        def on_recived(stream):
            stream.seek(0)
            self.robot.update_firmware(stream, int(size),
                                       self.cb_upload_callback)
            self.send_ok()
        self.simple_binary_receiver(size, on_recived)

    def update_mbfw(self, mimetype, ssize):
        size = int(ssize)

        def on_recived(stream):
            stream.seek(0)
            self.robot._backend.update_atmel(stream, int(size),
                                             self.cb_upload_callback)
            self.send_ok()
        self.simple_binary_receiver(size, on_recived)

    def start_play(self):
        self.robot.start_play()
        self.send_ok()

    def pause_play(self):
        self.robot.pause_play()
        self.send_ok()

    def resume_play(self):
        self.robot.abort_play()
        self.send_ok()

    def abort_play(self):
        self.robot.resume_play()
        self.send_ok()

    def quit_play(self):
        self.robot.quit_play()
        self.send_ok()

    def maintain_update_hbfw(self, mimetype, ssize):
        size = int(ssize)

        def update_cb(swap):
            def nav_cb(robot, *args):
                if args[0] == "UPLOADING":
                    self.send_json(status="uploading", sent=int(args[1]))
                elif args[0] == "WRITE":
                    self.send_json(status="operating",
                                   stage=["UPDATE_THFW", "WRITE"],
                                   written=size - int(args[1]))

                    self.send_json(status="update_hbfw", stage="WRITE",
                                   written=size - int(args[1]))
                else:
                    self.send_json(status="operating",
                                   stage=["UPDATE_THFW", args[0]])

                    self.send_json(status="update_hbfw", stage=args[0])
            size = swap.truncate()
            swap.seek(0)

            try:
                self.task.update_hbfw(swap, size, nav_cb)
                self.send_ok()
            except RobotError as e:
                self.send_error(*e.args)
            except Exception as e:
                logger.exception("ERR")
                self.send_fatal("UNKNOWN_ERROR", e.args)

        self.simple_binary_receiver(size, update_cb)

    def task_begin_scan(self):
        self.task = self.robot.scan()
        self.send_ok(task="scan")

    def task_begin_maintain(self):
        self.task = self.robot.maintain()
        self.send_ok(task="maintain")

    def task_begin_raw(self):
        self.task = self.robot.raw()
        self.raw_sock = RawSock(self.task.sock, self)
        self.rlist.append(self.raw_sock)
        self.send_ok(task="raw")

    def task_quit(self):
        self.task.quit()
        self.task = None
        self.send_ok(task="")

    def maintain_home(self):
        self.task.home()
        self.send_ok()

    def maintain_calibrating(self, *args):
        def callback(robot, *args):
            self.send_json(status="debug", text=" ".join(args))

        if "clean" in args:
            ret = self.task.calibration(process_callback=callback, clean=True)
        else:
            ret = self.task.calibration(process_callback=callback)
        self.send_json(status="ok", data=ret, error=(max(*ret) - min(*ret)))

    def maintain_zprobe(self, *args):
        def callback(robot, *args):
            self.send_json(status="operating", stage=["ZPROBE"])
            # TODO: PROTOCOL
            self.send_json(status="debug", text=" ".join(args))

        if len(args) > 0:
            ret = self.task.manual_level(float(args[0]))
        else:
            ret = self.task.zprobe(process_callback=callback)

        self.send_json(status="ok", data=ret)

    def maintain_load_filament(self, index, temp):
        def nav(robot, *args):
            self.send_json(status="operating", stage=args)
            # TODO: PROTOCOL
            self.send_json(status="loading", nav=" ".join(args))

        self.task.load_filament(int(index), float(temp), nav)
        self.send_ok()

    def maintain_unload_filament(self, index, temp):
        def nav(robot, *args):
            self.send_json(status="operating", stage=args)
            # TODO: PROTOCOL
            self.send_json(status="unloading", nav=args)
        self.task.unload_filament(int(index), float(temp), nav)
        self.send_ok()

    def maintain_headinfo(self):
        info = self.task.head_info()
        if "head_module" not in info:
            if "TYPE" in info:
                info["head_module"] = info.get("TYPE")
            elif "module" in info:
                info["head_module"] = info.get("module")

        if "version" not in info:
            info["version"] = info["VERSION"]
        self.send_ok(cmd="headinfo", **info)

    def maintain_headstatus(self):
        status = self.task.head_status()
        self.send_ok(**status)

    def report_play(self):
        data = self.robot.report_play()
        data["cmd"] = "report"
        self.send_ok(**data)

    def scan_oneshot(self):
        images = self.task.oneshot()
        for mimetype, buf in images:
            self.send_binary_buffer(mimetype, buf)
        self.send_ok()

    def scanimages(self):
        images = self.task.scanimages()
        for mimetype, buf in images:
            self.send_binary_buffer(mimetype, buf)
        self.send_ok()

    def scan_forward(self):
        self.task.forward()
        self.send_ok()

    def scan_backward(self):
        self.task.backward()
        self.send_ok()

    def scan_step(self, length):
        self.task.step_length(float(length))
        self.send_ok()

    def play_info(self):
        metadata, images = self.robot.play_info()
        # TODO: PROTOCOL
        metadata["status"] = "playinfo"
        self.send_json(metadata)

        for mime, buf in images:
            self.send_binary_begin(mime, len(buf))
            self.send_binary(buf)
        self.send_ok()

    def config_set(self, key, value):
        self.robot.config[key] = value
        self.send_json(status="ok", cmd="set", key=key)

    def config_get(self, key):
        self.send_json(status="ok", cmd="get", key=key,
                       value=self.robot.config[key])

    def config_del(self, key):
        del self.robot.config[key]
        self.send_json(status="ok", cmd="del", key=key)

    def on_raw_message(self, message):
        if message == "quit" or message == "task quit":
            self.rlist.remove(self.raw_sock)
            self.raw_sock = None
            self.task.quit()
            self.send_text('{"status": "ok", "task": ""}')
        else:
            self.raw_sock.sock.send(message.encode() + b"\n")


class RawSock(object):
    def __init__(self, sock, ws):
        self.sock = sock
        self.ws = ws

    def fileno(self):
        return self.sock.fileno()

    def on_read(self):
        buf = self.sock.recv(128)
        if buf:
            self.ws.send_json(status="raw",
                              text=buf.decode("ascii", "replace"))
        else:
            self.ws.rlist.remove(self)
            self.ws.send_fatal("DISCONNECTED")
