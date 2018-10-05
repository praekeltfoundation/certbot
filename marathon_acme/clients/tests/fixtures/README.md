# Generating test certificates
To generate test certificates [CFSSL](https://github.com/cloudflare/cfssl) is
recommended. If you're on a Mac you can run:
```
brew install cfssl
```

## Generating new certificates
New test certificates can be generated as follows:
```shell
DOMAIN=vault.example.org
cfssl gencert -config=config.json -profile=server -ca=ca.pem -ca-key=ca-key.pem \
  -cn=$DOMAIN -hostname=$DOMAIN,localhost csr.json | cfssljson -bare vault-server

DOMAIN=marathon-acme.example.org
cfssl gencert -config=config.json -profile=client -ca=ca.pem -ca-key=ca-key.pem \
  -cn=$DOMAIN -hostname=$DOMAIN,localhost csr.json | cfssljson -bare vault-client

cfssl gencert -config=config.json -profile=client -ca=ca2.pem -ca-key=ca2-key.pem \
  -cn=$DOMAIN -hostname=$DOMAIN,localhost csr.json | cfssljson -bare vault-client2
```

This will generate a few files. You can delete the CSR files: `rm *.csr`

If you want to add additional SANs to the certificate, the `-hostname` option
can take a list of comma-separated values.

## Generating the CAs
If for some reason you need to regenerate the CA certificates, you can do so
with this command:
```shell
cfssl gencert -initca -cn="Test Certificate Authority" csr.json \
  | cfssljson -bare ca

cfssl gencert -initca -cn="Test Certificate Authority 2" csr.json \
  | cfssljson -bare ca2
```
You can then delete the CSR file: `rm *.csr`
