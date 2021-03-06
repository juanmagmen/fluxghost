
import importlib
import re


ROUTES = [
    (re.compile("echo"),
     "fluxghost.websocket.echo.WebsocketEcho"),
    (re.compile("ver"),
     "fluxghost.websocket.ver.WebsocketVer"),
    (re.compile("config"),
     "fluxghost.websocket.config.WebsocketConfig"),
    (re.compile("3d-scan-modeling"),
     "fluxghost.websocket.scan_modeling.Websocket3DScannModeling"),
    (re.compile("bitmap-laser-parser"),
     "fluxghost.websocket.laser_bitmap_parser.WebsocketLaserBitmapParser"),
    (re.compile("svg-laser-parser"),
     "fluxghost.websocket.laser_svg_parser.WebsocketLaserSvgParser"),
    (re.compile("pen-svg-parser"),
     "fluxghost.websocket.pen_svg_parser.WebsocketPenSvgParser"),
    (re.compile("fcode-reader"),
     "fluxghost.websocket.fcode_reader.WebsocketFcodeReader"),
    (re.compile("discover"),
     "fluxghost.websocket.discover.WebsocketDiscover"),
    (re.compile("touch"),
     "fluxghost.websocket.touch.WebsocketTouch"),
    (re.compile("control/(?P<serial>[0-9a-fA-F]{32})"),
     "fluxghost.websocket.control.WebsocketControl"),
    (re.compile("camera/(?P<serial>[0-9a-fA-F]{32})"),
     "fluxghost.websocket.camera.WebsocketCamera"),
    (re.compile("3d-scan-control/(?P<serial>[0-9a-fA-F]{32})"),
     "fluxghost.websocket.scan_control.Websocket3DScanControl"),
    (re.compile("3dprint-slicing"),
     "fluxghost.websocket.stl_slicing_parser.Websocket3DSlicing"),
    (re.compile("usb-config"),
     "fluxghost.websocket.usb_config.WebsocketUsbConfig"),
    (re.compile("upnp-config"),
     "fluxghost.websocket.upnp_ws.WebsocketUpnp")]


def get_match_ws_service(path):
    for exp, module_path in ROUTES:
        match = exp.match(path)
        if match:
            module_name, klass_name = module_path.rsplit(".", 1)
            module_instance = importlib.import_module(module_name)
            klass = module_instance.__getattribute__(klass_name)
            return klass, match.groupdict()
    return None, None
