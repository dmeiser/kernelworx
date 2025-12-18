#!/bin/bash
# Setup script for local development with local.dev.appworx.app

set -e

echo "🚀 Setting up local development environment..."
echo ""

# Check if running on Linux/macOS
if [[ "$OSTYPE" == "linux"* ]] || [[ "$OSTYPE" == "darwin"* ]]; then
    # Check if hosts entry exists
    if grep -q "local.dev.appworx.app" /etc/hosts; then
        echo "✅ /etc/hosts already configured"
    else
        echo "📝 Adding local.dev.appworx.app to /etc/hosts..."
        echo "   (You may be prompted for your password)"
        echo "127.0.0.1  local.dev.appworx.app" | sudo tee -a /etc/hosts > /dev/null
        echo "✅ Added to /etc/hosts"
    fi
else
    echo "⚠️  Windows detected. Please manually add this line to C:\\Windows\\System32\\drivers\\etc\\hosts:"
    echo "   127.0.0.1  local.dev.appworx.app"
    echo ""
fi

# Check if certificates exist and are valid
CERT_VALID=false
if [ -f ".cert/cert-local.pem" ] && [ -f ".cert/key-local.pem" ]; then
    # Check if certificate contains the correct domain
    if openssl x509 -in .cert/cert-local.pem -text -noout | grep -q "local.dev.appworx.app"; then
        echo "✅ SSL certificates already exist and are valid"
        CERT_VALID=true
    else
        echo "⚠️  Existing certificate doesn't include local.dev.appworx.app"
        echo "🔐 Regenerating SSL certificates..."
    fi
else
    echo "🔐 Generating SSL certificates for local.dev.appworx.app..."
fi

if [ "$CERT_VALID" = false ]; then
    mkdir -p .cert
    openssl req -x509 -newkey rsa:2048 \
        -keyout .cert/key-local.pem \
        -out .cert/cert-local.pem \
        -days 365 -nodes \
        -subj "/CN=local.dev.appworx.app" \
        -addext "subjectAltName=DNS:local.dev.appworx.app" 2>/dev/null
    echo "✅ SSL certificates generated"
    
    # Verify the certificate was created correctly
    if openssl x509 -in .cert/cert-local.pem -text -noout | grep -q "local.dev.appworx.app"; then
        echo "✅ Certificate verification passed"
    else
        echo "❌ Warning: Certificate may not be configured correctly"
    fi
fi

# Check if .env.local exists
if [ -f ".env.local" ]; then
    echo "✅ .env.local already exists"
else
    echo "📋 Creating .env.local from current .env..."
    if [ -f ".env" ]; then
        cat .env | sed 's|https://dev.kernelworx.app|https://local.dev.appworx.app:5173|g' > .env.local
        echo "✅ .env.local created"
    else
        echo "⚠️  .env not found. Please create .env.local manually."
    fi
fi

echo ""
echo "✨ Setup complete!"
echo ""
echo "📚 Next steps:"
echo "   1. Deploy CDK changes: cd ../cdk && ./deploy.sh"
echo "   2. Start dev server: npm run dev"
echo "   3. Open browser: https://local.dev.appworx.app:5173"
echo ""
echo "💡 To trust the SSL certificate and avoid browser warnings:"
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "   sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain .cert/cert-local.pem"
elif [[ "$OSTYPE" == "linux"* ]]; then
    echo "   sudo cp .cert/cert-local.pem /usr/local/share/ca-certificates/local.dev.appworx.app.crt"
    echo "   sudo update-ca-certificates"
fi
echo ""
