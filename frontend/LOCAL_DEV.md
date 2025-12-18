# Local Development with local.dev.appworx.app

This guide explains how to develop locally using the domain `local.dev.appworx.app` instead of `localhost`.

## Why use a custom local domain?

- **HTTPS support**: Social OAuth providers (Google, Facebook, Apple) require HTTPS
- **Cookie consistency**: Matches production cookie domain settings
- **Realistic testing**: Tests your app in an environment closer to production

## Setup Instructions

### 1. Add DNS entry to your hosts file

Add this line to your `/etc/hosts` file:

```
127.0.0.1  local.dev.appworx.app
```

On Linux/macOS:
```bash
sudo nano /etc/hosts
# Add the line above, then save (Ctrl+O, Enter, Ctrl+X)
```

On Windows (run as Administrator):
```
notepad C:\Windows\System32\drivers\etc\hosts
# Add the line above, then save
```

### 2. Generate SSL certificate (already done)

The project already has SSL certificates in `frontend/.cert/` (gitignored). If you need to regenerate them:

```bash
cd frontend
mkdir -p .cert
cd .cert

# Generate self-signed certificate
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes \
  -subj "/CN=local.dev.appworx.app" \
  -addext "subjectAltName=DNS:local.dev.appworx.app"
```

### 3. Trust the certificate (optional but recommended)

To avoid browser security warnings:

**macOS:**
```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain .cert/cert.pem
```

**Linux (Ubuntu/Debian):**
```bash
sudo cp .cert/cert.pem /usr/local/share/ca-certificates/local.dev.appworx.app.crt
sudo update-ca-certificates
```

**Windows:**
- Double-click `cert.pem`
- Click "Install Certificate"
- Choose "Local Machine"
- Select "Place all certificates in the following store"
- Browse to "Trusted Root Certification Authorities"
- Click Finish

### 4. Deploy CDK changes to update Cognito

The CDK stack now includes `https://local.dev.appworx.app:5173` in the Cognito callback URLs. Deploy the changes:

```bash
cd cdk
./deploy.sh
```

This updates the Cognito User Pool Client to allow redirects to your local domain.

### 5. Use the local environment file

The `.env.local` file is already configured with the correct OAuth redirect URLs. When you run the dev server, Vite will automatically use this file:

```bash
cd frontend
npm run dev
```

### 6. Access your app

Open your browser to:
```
https://local.dev.appworx.app:5173
```

**Note:** If you didn't trust the certificate, you'll see a security warning. Click "Advanced" and "Proceed anyway" (the connection is still encrypted, just self-signed).

## Switching back to localhost

To use `http://localhost:5173` instead:

1. Rename or delete `.env.local`
2. The app will fall back to `.env` which has the localhost URLs

## Troubleshooting

### "This site can't be reached"
- Check that you added the entry to `/etc/hosts`
- Try `ping local.dev.appworx.app` - it should resolve to `127.0.0.1`

### SSL certificate errors
- Make sure the certificate files exist in `frontend/.cert/`
- Regenerate the certificate if needed (see step 2)
- Trust the certificate (see step 3)

### OAuth redirect errors
- Ensure you deployed the CDK changes (step 4)
- Check that the callback URLs in Cognito match your local domain
- Clear your browser cookies and try again

### Port 5173 already in use
- Stop any other Vite dev servers
- Or change the port in `vite.config.ts` and update `.env.local` accordingly
