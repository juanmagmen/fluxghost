
from os import environ
import logging

from fluxclient.laser.laser_bitmap import LaserBitmap
from .misc import BinaryUploadHelper, BinaryHelperMixin, OnTextMessageMixin

logger = logging.getLogger("API.LASER.BITMAP")

MODE_PRESET = "preset"
MODE_MANUALLY = "manually"


def laser_bitmap_parser_api_mixin(cls):
    class LaserBitmapParserApi(BinaryHelperMixin, OnTextMessageMixin, cls):
        # images, it will like
        # [
        #    [(x1, y1, x2, z2), (w, h), bytes],
        #    ....
        # ]
        images = []
        _m_laser_bitmap = None

        def __init__(self, *args):
            super().__init__(*args)
            self.cmd_mapping = {
                'upload': [self.begin_recv_image],
                'go': [self.go],
                'set_params': [self.set_params],
                'clear_imgs': [self.clear_imgs],
                'meta_option': [self.meta_option]
            }

        @property
        def m_laser_bitmap(self):
            if self._m_laser_bitmap is None:
                self._m_laser_bitmap = LaserBitmap()
            return self._m_laser_bitmap

        def begin_recv_image(self, message):
            options = message.split()
            w, h = int(options[0]), int(options[1])
            x1, y1, x2, y2 = (float(o) for o in options[2:6])
            rotation = float(options[6])
            thres = int(options[7])

            image_size = w * h

            logger.debug("  Start recv image at [%.4f, %.4f][%.4f,%.4f] x [%i, %i], rotation = %.4f thres = %d" %
                         (x1, y1, x2, y2, w, h, rotation, thres))
            # if image_size > 1024 * 1024 * 8:
            #     raise RuntimeError("IMAGE_TOO_LARGE")

            helper = BinaryUploadHelper(image_size, self.end_recv_image,
                                        (x1, y1, x2, y2), (w, h), rotation, thres)
            self.set_binary_helper(helper)
            self.send_continue()

        def end_recv_image(self, buf, position, size, rotation, thres):
            self.images.append((position, size, rotation, thres, buf))
            self.send_text('{"status": "accept"}')

        def set_params(self, params):
            key, value = params.split()
            self.m_laser_bitmap.set_params(key, value)
            self.send_ok()

        def meta_option(self, params):
            key, value = params.split()
            self.m_laser_bitmap.ext_metadata[key] = value
            self.send_ok()

        def clear_imgs(self, params):
            logger.debug('clear_imgs')
            self.images = []
            self.m_laser_bitmap.reset_image()
            self.send_ok()

        def go(self, *args):
            logger.debug('  start process images')
            self.send_progress('initializing', 0.03)

            layer_index = 0
            for position, size, rotation, thres, buf in self.images:
                layer_index += 1
                self.send_progress('processing image', (layer_index / len(self.images) * 0.6 + 0.03))
                self.m_laser_bitmap.add_image(buf, size[0], size[1], position[0], position[1], position[2], position[3], rotation, thres)
                logger.debug("add image at %s pixel: %s" % (position, size))

            logger.debug("add image finished, generating gcode")
            self.send_progress('generating fcode', 0.97)
            if '-g' in args:
                output_binary = self.m_laser_bitmap.gcode_generate().encode()
                time_need = 0
            else:
                output_binary, m_GcodeToFcode = self.m_laser_bitmap.fcode_generate()
                time_need = float(m_GcodeToFcode.md['TIME_COST'])
                # ######### fake code  ########################
                if environ.get("flux_debug") == '1':
                    with open('output.fc', 'wb') as f:
                        f.write(output_binary)
                # #############################################

            self.send_progress('finishing', 1.0)
            self.send_text('{"status": "complete", "length": %d, "time": %.3f}' % (len(output_binary), time_need))
            self.send_binary(output_binary)
            logger.debug("laser bitmap finished")
    return LaserBitmapParserApi
