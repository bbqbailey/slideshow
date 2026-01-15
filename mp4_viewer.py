#!/usr/bin/env python3
from http.server import SimpleHTTPRequestHandler, HTTPServer
import ssl
import os

class MP4ViewerHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        # Serve the MP4 file for the driveway-1400.mp4
        if self.path == "/slideshow":
            # Correct date format (YYYYMMDD)
            date = "20260115"  # Correct date format without dashes
            camera_location = "driveway"
            video_filename = "driveway-1400.mp4"
            
            # Correct file path based on the accurate date format
            video_path = f"/media/CameraSnapshots/SecurityCameraSnapshots/archive/{date}/{camera_location}/{video_filename}"

            if os.path.exists(video_path):
                self.send_response(200)
                self.send_header("Content-type", "video/mp4")
                self.send_header("Content-Disposition", f'inline; filename="{video_filename}"')
                self.end_headers()

                with open(video_path, "rb") as video_file:
                    self.wfile.write(video_file.read())
            else:
                self.send_error(404, "File Not Found")
        else:
            super().do_GET()

def run(server_class=HTTPServer, handler_class=MP4ViewerHandler, port=8000):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    
    # Set up SSL using the existing certificate and key files
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile="/home/superben/myProjects/python/slideshow/certs/hottub.crt",
                            keyfile="/home/superben/myProjects/python/slideshow/certs/hottub.key")
    
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    
    print(f"Serving MP4 viewer on port {port}...")
    httpd.serve_forever()

if __name__ == "__main__":
    run()

