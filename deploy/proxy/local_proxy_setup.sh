#!/bin/bash
# Expose your local laptop as a residential proxy for GCP testing
# This uses your home IP which YouTube won't block!

set -e

echo "🏠 Local Residential Proxy Setup"
echo "================================="
echo ""

# Check for required tools
check_tool() {
    if ! command -v "$1" &> /dev/null; then
        echo "❌ $1 is not installed"
        return 1
    fi
    echo "✅ $1 found"
    return 0
}

echo "Checking dependencies..."

# Check for Docker or Squid
if ! check_tool docker && ! check_tool squid; then
    echo ""
    echo "Please install Docker:"
    echo "  brew install --cask docker"
    echo ""
    echo "Or install Squid directly:"
    echo "  brew install squid"
    exit 1
fi

# Check for ngrok
if ! check_tool ngrok; then
    echo ""
    echo "Please install ngrok:"
    echo "  brew install ngrok"
    echo ""
    echo "Then authenticate:"
    echo "  ngrok config add-authtoken YOUR_TOKEN"
    echo "  (Get token at https://dashboard.ngrok.com/get-started/your-authtoken)"
    exit 1
fi

echo ""
echo "All dependencies found!"
echo ""

# Configuration
PROXY_PORT=3128
PROXY_USER="videoscraper"
PROXY_PASSWORD=$(openssl rand -hex 8)

echo "📝 Proxy Credentials:"
echo "   Username: $PROXY_USER"
echo "   Password: $PROXY_PASSWORD"
echo ""

# Create Squid config directory
PROXY_DIR="$HOME/.videoscraper-proxy"
mkdir -p "$PROXY_DIR"

# Create Squid configuration
cat > "$PROXY_DIR/squid.conf" << EOF
# Squid Proxy for Local Residential IP Testing
http_port 3128

# Basic authentication
auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwords
auth_param basic realm VideoScraper Local Proxy
auth_param basic credentialsttl 24 hours
acl authenticated proxy_auth REQUIRED

# Access control
http_access allow authenticated
http_access deny all

# Hide proxy headers (important for YouTube)
forwarded_for delete
via off
request_header_access X-Forwarded-For deny all
request_header_access Via deny all
request_header_access Proxy-Connection deny all

# Disable caching
cache deny all

# Logging
access_log stdio:/dev/stdout
cache_log stdio:/dev/stderr
EOF

# Create password file
if command -v htpasswd &> /dev/null; then
    htpasswd -bc "$PROXY_DIR/passwords" "$PROXY_USER" "$PROXY_PASSWORD" 2>/dev/null
else
    # Use openssl as fallback
    HASH=$(openssl passwd -apr1 "$PROXY_PASSWORD")
    echo "$PROXY_USER:$HASH" > "$PROXY_DIR/passwords"
fi

echo "✅ Configuration created in $PROXY_DIR"
echo ""

# Start Squid proxy
echo "🚀 Starting Squid proxy on port $PROXY_PORT..."

if command -v docker &> /dev/null; then
    # Stop any existing container
    docker rm -f videoscraper-proxy 2>/dev/null || true
    
    # Start Squid in Docker
    docker run -d \
        --name videoscraper-proxy \
        -p $PROXY_PORT:3128 \
        -v "$PROXY_DIR/squid.conf:/etc/squid/squid.conf:ro" \
        -v "$PROXY_DIR/passwords:/etc/squid/passwords:ro" \
        ubuntu/squid:latest
    
    echo "✅ Squid proxy started in Docker"
else
    # Use local Squid
    sudo cp "$PROXY_DIR/squid.conf" /usr/local/etc/squid.conf
    sudo cp "$PROXY_DIR/passwords" /usr/local/etc/squid/passwords
    brew services restart squid
    echo "✅ Squid proxy started via Homebrew"
fi

# Wait for proxy to start
sleep 3

# Test local proxy
echo ""
echo "🧪 Testing local proxy..."
LOCAL_IP=$(curl -s -x "http://$PROXY_USER:$PROXY_PASSWORD@localhost:$PROXY_PORT" https://api.ipify.org 2>/dev/null || echo "failed")

if [ "$LOCAL_IP" = "failed" ]; then
    echo "❌ Local proxy test failed. Check the logs:"
    echo "   docker logs videoscraper-proxy"
    exit 1
fi

echo "✅ Local proxy working! Your residential IP: $LOCAL_IP"
echo ""

# Start ngrok tunnel
echo "🌐 Starting ngrok tunnel..."
echo ""

# Kill any existing ngrok
pkill -f "ngrok tcp" 2>/dev/null || true
sleep 1

# Start ngrok in background
ngrok tcp $PROXY_PORT --log=stdout > "$PROXY_DIR/ngrok.log" 2>&1 &
NGROK_PID=$!

echo "Waiting for ngrok to connect..."
sleep 5

# Get ngrok URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | grep -o '"public_url":"tcp://[^"]*"' | cut -d'"' -f4 | head -1)

if [ -z "$NGROK_URL" ]; then
    echo "❌ Failed to get ngrok URL. Check if ngrok is authenticated:"
    echo "   ngrok config add-authtoken YOUR_TOKEN"
    echo ""
    echo "ngrok logs:"
    cat "$PROXY_DIR/ngrok.log"
    exit 1
fi

# Parse ngrok URL
NGROK_HOST=$(echo "$NGROK_URL" | sed 's|tcp://||' | cut -d: -f1)
NGROK_PORT=$(echo "$NGROK_URL" | sed 's|tcp://||' | cut -d: -f2)

echo ""
echo "=========================================="
echo "🎉 LOCAL RESIDENTIAL PROXY READY!"
echo "=========================================="
echo ""
echo "📍 Your Residential IP: $LOCAL_IP"
echo ""
echo "🔗 Proxy URL for GCP:"
echo "   http://$PROXY_USER:$PROXY_PASSWORD@$NGROK_HOST:$NGROK_PORT"
echo ""
echo "📋 To use in GCP Cloud Run, run:"
echo ""
echo "   gcloud run deploy videoscraper-demo \\"
echo "       --image gcr.io/videoscraper-demo-1766976481/videoscraper-demo \\"
echo "       --set-env-vars \"PROXY_PROVIDER=custom,PROXY_HOST=$NGROK_HOST,PROXY_PORT=$NGROK_PORT,PROXY_USERNAME=$PROXY_USER,PROXY_PASSWORD=$PROXY_PASSWORD\" \\"
echo "       --region us-central1 \\"
echo "       --project videoscraper-demo-1766976481"
echo ""
echo "🧪 Test the proxy remotely:"
echo "   curl -x http://$PROXY_USER:$PROXY_PASSWORD@$NGROK_HOST:$NGROK_PORT https://api.ipify.org"
echo ""
echo "⚠️  Keep this terminal open! The proxy stops when you close it."
echo ""
echo "To stop: Ctrl+C or run: docker rm -f videoscraper-proxy && pkill ngrok"
echo ""

# Save proxy URL for easy access
echo "http://$PROXY_USER:$PROXY_PASSWORD@$NGROK_HOST:$NGROK_PORT" > "$PROXY_DIR/proxy_url.txt"
echo "Proxy URL saved to: $PROXY_DIR/proxy_url.txt"

# Keep script running
echo ""
echo "Press Ctrl+C to stop the proxy..."
wait $NGROK_PID

