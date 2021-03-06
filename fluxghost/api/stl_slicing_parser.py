
import subprocess
import logging
import os

from fluxclient.printer.stl_slicer import StlSlicer, StlSlicerCura
from fluxclient import check_platform
from .misc import BinaryUploadHelper, BinaryHelperMixin, OnTextMessageMixin

logger = logging.getLogger("API.SLICING")


def get_default_cura():
    if 'cura' in os.environ:
        engine_path = os.environ["cura"]
    else:
        p = check_platform()
        if p[0] == 'OSX':
            engine_path = "/Applications/Cura/Cura.app/Contents/Resources/CuraEngine"
        elif p[0] == "Linux":
            engine_path = "/usr/share/cura/CuraEngine"
        elif p[0] == "Windows":
            if p[1] == '64bit':
                engine_path = "C:\Program Files (x86)\Cura_15.04.5\CuraEngine.exe"
            elif p[1] == '32bit':
                engine_path = "C:\Program Files\Cura_15.04.5\CuraEngine.exe"
        else:
            raise RuntimeError("Unknow Platform: {}".format(p))
    return engine_path


def stl_slicing_parser_api_mixin(cls):
    class StlSlicingParserApi(BinaryHelperMixin, OnTextMessageMixin, cls):
        """
        This websocket is use to slice a stl/obj model
        """
        POOL_TIME = 30.0

        def __init__(self, *args):
            super().__init__(*args)

            self.m_stl_slicer = StlSlicer('')
            self._change_engine('slic3r default')
            # self.change_engine('cura default')

            self.cmd_mapping = {
                'upload': [self.begin_recv_stl, 'upload'],
                'upload_image': [self.begin_recv_stl, 'upload_image'],
                'set': [self.set],
                'go': [self.gcode_generate],
                'delete': [self.delete],
                'advanced_setting': [self.advanced_setting],
                'get_path': [self.get_path],
                'duplicate': [self.duplicate],
                'meta_option': [self.meta_option],
                'begin_slicing': [self.begin_slicing],
                'end_slicing': [self.end_slicing],
                'report_slicing': [self.report_slicing],
                'get_result': [self.get_result],
                'change_engine': [self.change_engine],
                'check_engine': [self.check_engine],

            }
            self.ext_metadata = {}

        def begin_recv_stl(self, params, flag):
            if flag == 'upload':
                params = params.split()

                if len(params) == 2:
                    name, file_length = params
                    buf_type = 'stl'
                elif len(params) == 3:
                    name, file_length, buf_type = params
            elif flag == 'upload_image':
                # useless
                name = ''
                buf_type = ''
                file_length = params
                logger.debug('upload_image {}'.format(file_length))

            if int(file_length) == 0:
                self.send_error('12', info='empty file!')
            else:
                helper = BinaryUploadHelper(int(file_length), self.end_recv_stl, name, flag, buf_type)
                self.set_binary_helper(helper)

                self.send_continue()

        def end_recv_stl(self, buf, *args):
            if args[1] == 'upload':
                logger.debug('upload ' + args[0] + args[2])
                ret = self.m_stl_slicer.upload(args[0], buf, args[2])
                if ret:
                    self.send_ok()
                else:
                    self.send_error('15', info="File parsing fail")
                return
            elif args[1] == 'upload_image':
                ret = self.m_stl_slicer.upload_image(buf)
                self.send_ok()

        def duplicate(self, params):
            logger.debug('duplicate ' + params)
            name_in, name_out = params.split()
            flag = self.m_stl_slicer.duplicate(name_in, name_out)
            if flag:
                self.send_ok()
            else:
                self.send_error('13', info='{} not exist'.format(name_in))

        def set(self, params):
            params = params.split()
            assert len(params) == 10, 'wrong number of parameters %d' % len(params)
            name = params[0]
            position_x = float(params[1])
            position_y = float(params[2])
            position_z = float(params[3])
            rotation_x = float(params[4])
            rotation_y = float(params[5])
            rotation_z = float(params[6])
            scale_x = float(params[7])
            scale_y = float(params[8])
            scale_z = float(params[9])

            logger.debug('set {} {} {} {} {} {} {} {} {} {}'.format(name, position_x, position_y, position_z, rotation_x, rotation_y, rotation_z, scale_x, scale_y, scale_z))
            set_result = self.m_stl_slicer.set(name, [position_x, position_y, position_z, rotation_x, rotation_y, rotation_z, scale_x, scale_y, scale_z])
            if set_result == 'ok':
                self.send_ok()
            else:
                self.send_error('14', info=set_result)

        def advanced_setting(self, params):
            lines = params.split('\n')
            bad_lines = self.m_stl_slicer.advanced_setting(lines)
            if bad_lines != []:
                for line_num, err_msg in bad_lines:
                    self.send_error('7', info='line %d: %s' % (line_num, err_msg))
                    logger.debug('line %d: %s' % (line_num, err_msg))
            self.send_ok()

        def gcode_generate(self, params):
            raise RuntimeError('is this still working?')
            names = params.split()
            if names[-1] == '-g':
                output_type = '-g'
                names = names[:-1]
            elif names[-1] == '-f':
                output_type = '-f'
                names = names[:-1]
            else:
                output_type = '-f'
            output, metadata = self.m_stl_slicer.gcode_generate(names, self, output_type)
            # self.send_progress('finishing', 1.0)
            if output:
                self.send_text('{"slice_status": "complete", "length": %d, "time": %.3f, "filament_length": %.2f}' % (len(output), metadata[0], metadata[1]))
                self.send_binary(output)
                logger.debug('slicing finish')
            else:
                self.send_error(metadata)
                logger.debug('slicing fail')

        def begin_slicing(self, params):
            names = params.split()
            if names[-1] == '-g':
                output_type = '-g'
                names = names[:-1]
            elif names[-1] == '-f':
                output_type = '-f'
                names = names[:-1]
            else:
                output_type = '-f'
            self.m_stl_slicer.begin_slicing(names, self, output_type)
            self.send_ok()

        def end_slicing(self, *args):
            self.m_stl_slicer.end_slicing()
            self.send_ok()

        def report_slicing(self, *args):
            for m in self.m_stl_slicer.report_slicing():
                self.send_text(m)
            self.send_ok()

        def get_result(self, *args):
            if self.m_stl_slicer.output:
                self.send_ok(info=str(len(self.m_stl_slicer.output)))
                self.send_binary(self.m_stl_slicer.output)
            else:
                self.send_error('8', info='No result to send')

        def get_path(self, *args):
            path = self.m_stl_slicer.get_path()
            if path:
                self.send_text(path)
            else:
                self.send_error('9', info='No path data to send')

        def delete(self, params):
            name = params.rstrip()
            flag, message = self.m_stl_slicer.delete(name)
            if flag:
                self.send_ok()
            else:
                self.send_error('10', info=message)

        def meta_option(self, params):
            key, value = params.split()
            self.m_stl_slicer.ext_metadata[key] = value
            self.send_ok()

        def change_engine(self, params):
            """
            change_engine for front-end
            """
            logger.debug('change_engine ' + params)
            engine, engine_path = params.split()
            if self._change_engine(params):
                self.send_ok()
            else:
                self.send_error('11', info="wrong engine {}, should be 'cura' or 'slic3r'".format(engine))

        def _change_engine(self, params):
            """
            normal chaning engine
            """
            engine, engine_path = params.split()
            if engine == 'slic3r':
                logger.debug("Using slic3r()")
                if engine_path == 'default':
                    if 'slic3r' in os.environ:
                        engine_path = os.environ["slic3r"]
                    else:
                        engine_path = "../Slic3r/slic3r.pl"
                self.m_stl_slicer = StlSlicer(engine_path).from_other(self.m_stl_slicer)
            elif engine == 'cura':
                logger.debug("Using cura")
                if engine_path == 'default':
                    engine_path = get_default_cura()
                self.m_stl_slicer = StlSlicerCura(engine_path).from_other(self.m_stl_slicer)
            else:
                return False
            return True

        def check_engine(self, params):
            engine = params
            error_code, ret = self._check_engine(engine)
            if error_code == 0:
                self.send_ok()
            elif error_code < 5:
                self.send_error(str(error_code), info=ret)
            else:
                self.send_fatal(str(error_code), info=ret)

        def _check_engine(self, params):
            engine, engine_path = params.split()
            if engine == 'cura':
                if engine_path == 'default':
                    engine_path = get_default_cura()

                if os.path.isfile(engine_path):
                    try:
                        out = subprocess.check_output(engine_path, stderr=subprocess.STDOUT, timeout=5)
                    except Exception:
                        logger.exception("Unknown error")
                        return 1, 'execution fail'
                    else:
                        out = out.split(b'\n')[0].rstrip()
                        if out.startswith(b'Cura_SteamEngine version'):
                            if out.endswith(b'15.04.5'):
                                return 0, 'ok'
                            else:
                                return 2, 'version error:{}'.format(out.split()[-1].decode())
                        else:
                            return 3, '{} is not cura'.format(engine_path)
                else:
                    return 4, '{} not exist'.format(engine_path)
            elif engine == 'slic3r':
                return 0, 'ok'
            else:
                return 5, '{} check not supported'.format(engine)
    return StlSlicingParserApi
