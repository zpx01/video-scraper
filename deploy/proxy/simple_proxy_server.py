#!/usr/bin/env python3
"""
Simple HTTP Proxy Server for exposing your local residential IP.
No external dependencies required - uses only Python stdlib.

Usage:
    python simple_proxy_server.py

Then use ngrok to expose it:
    ngrok tcp 8888
"""

import base64
import http.server
import os
import socket
import socketserver
import sys
import threading
import urllib.request
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlparse

# Configuration
PROXY_PORT = int(os.getenv("PROXY_PORT", "8888"))
PROXY_USER = os.getenv("PROXY_USER", "videoscraper")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD", "testpass123")


def check_auth(headers):
    """Verify proxy authentication."""
    auth_header = headers.get("Proxy-Authorization", "")
    if not auth_header.startswith("Basic "):
        return False
    
    try:
        encoded = auth_header[6:]
        decoded = base64.b64decode(encoded).decode("utf-8")
        username, password = decoded.split(":", 1)
        return username == PROXY_USER and password == PROXY_PASSWORD
    except Exception:
        return False


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    """Handle proxy requests."""
    
    # Disable logging for cleaner output
    def log_message(self, format, *args):
        print(f"[PROXY] {args[0]}")
    
    def do_CONNECT(self):
        """Handle HTTPS CONNECT requests (tunnel mode)."""
        if not check_auth(self.headers):
            self.send_response(407)
            self.send_header("Proxy-Authenticate", 'Basic realm="Proxy"')
            self.end_headers()
            return
        
        try:
            # Parse target
            host, port = self.path.split(":")
            port = int(port)
            
            # Connect to target
            target = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            target.connect((host, port))
            
            # Send success response
            self.send_response(200, "Connection Established")
            self.end_headers()
            
            # Tunnel data between client and target
            self._tunnel(self.connection, target)
            
        except Exception as e:
            self.send_error(502, f"Bad Gateway: {e}")
        finally:
            try:
                target.close()
            except:
                pass
    
    def _tunnel(self, client, target):
        """Tunnel data between client and target."""
        client.setblocking(False)
        target.setblocking(False)
        
        while True:
            # Try reading from client
            try:
                data = client.recv(8192)
                if data:
                    target.sendall(data)
                elif data == b"":
                    break
            except BlockingIOError:
                pass
            except Exception:
                break
            
            # Try reading from target
            try:
                data = target.recv(8192)
                if data:
                    client.sendall(data)
                elif data == b"":
                    break
            except BlockingIOError:
                pass
            except Exception:
                break
    
    def do_GET(self):
        """Handle HTTP GET requests."""
        self._proxy_request("GET")
    
    def do_POST(self):
        """Handle HTTP POST requests."""
        self._proxy_request("POST")
    
    def do_PUT(self):
        """Handle HTTP PUT requests."""
        self._proxy_request("PUT")
    
    def do_DELETE(self):
        """Handle HTTP DELETE requests."""
        self._proxy_request("DELETE")
    
    def do_HEAD(self):
        """Handle HTTP HEAD requests."""
        self._proxy_request("HEAD")
    
    def _proxy_request(self, method):
        """Proxy an HTTP request."""
        if not check_auth(self.headers):
            self.send_response(407)
            self.send_header("Proxy-Authenticate", 'Basic realm="Proxy"')
            self.end_headers()
            return
        
        try:
            # Parse URL
            parsed = urlparse(self.path)
            
            # Get host and port
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"
            
            # Read request body if present
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else None
            
            # Create connection
            if parsed.scheme == "https":
                conn = HTTPSConnection(host, port)
            else:
                conn = HTTPConnection(host, port)
            
            # Forward headers (excluding hop-by-hop)
            forward_headers = {}
            hop_by_hop = {"proxy-authorization", "proxy-connection", "connection", 
                          "keep-alive", "te", "trailers", "transfer-encoding", "upgrade"}
            
            for key, value in self.headers.items():
                if key.lower() not in hop_by_hop:
                    forward_headers[key] = value
            
            # Make request
            conn.request(method, path, body, forward_headers)
            response = conn.getresponse()
            
            # Send response
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in hop_by_hop:
                    self.send_header(key, value)
            self.end_headers()
            
            # Send body
            self.wfile.write(response.read())
            conn.close()
            
        except Exception as e:
            self.send_error(502, f"Bad Gateway: {e}")


class ThreadedProxyServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Threaded proxy server for handling multiple connections."""
    allow_reuse_address = True
    daemon_threads = True


def get_local_ip():
    """Get local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"


def main():
    print("=" * 50)
    print("🏠 Local Residential Proxy Server")
    print("=" * 50)
    print()
    print(f"📝 Credentials:")
    print(f"   Username: {PROXY_USER}")
    print(f"   Password: {PROXY_PASSWORD}")
    print()
    print(f"🔧 Starting proxy on port {PROXY_PORT}...")
    
    server = ThreadedProxyServer(("0.0.0.0", PROXY_PORT), ProxyHandler)
    
    local_ip = get_local_ip()
    print()
    print(f"✅ Proxy running!")
    print(f"   Local:  http://{PROXY_USER}:{PROXY_PASSWORD}@localhost:{PROXY_PORT}")
    print(f"   LAN:    http://{PROXY_USER}:{PROXY_PASSWORD}@{local_ip}:{PROXY_PORT}")
    print()
    print("📋 Next steps:")
    print("   1. Install ngrok: brew install ngrok")
    print("   2. Authenticate: ngrok config add-authtoken YOUR_TOKEN")
    print("   3. Expose proxy: ngrok tcp 8888")
    print("   4. Use the ngrok URL in your GCP deployment")
    print()
    print("🧪 Test locally:")
    print(f"   curl -x http://{PROXY_USER}:{PROXY_PASSWORD}@localhost:{PROXY_PORT} https://api.ipify.org")
    print()
    print("Press Ctrl+C to stop...")
    print()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Proxy stopped")
        server.shutdown()


if __name__ == "__main__":
    main()

