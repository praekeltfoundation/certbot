# Generating test certificates
To generate test certificates [CFSSL](https://github.com/cloudflare/cfssl) is
recommended. If you're on a Mac you can run:
```
brew install cfssl
```

## Generating new certificates
New test certificates can be generated as follows:
```shell
DOMAIN=marathon-acme.example.org
cfssl gencert -ca=ca.pem -ca-key=ca-key.pem -cn=$DOMAIN -hostname=$DOMAIN csr.json \
  | cfssljson -bare cert
```

This will generate 3 files: `cert.csr`, `cert.pem`, and `cert-key.pem`. Next,
concatenate the private key and certificate files together:
```shell
cat cert-key.pem cert.pem ca.pem > $DOMAIN.pem
```

You can then delete the individual cert files: `rm cert*`

If you want to add additional SANs to the certificate, the `-hostname` option
can take a list of comma-separated values.

## Generating the CA
If for some reason you need to regenerate the CA certificates, you can do so
with this command:
```shell
cfssl gencert -initca -cn="Test Certificate Authority" csr.json \
  | cfssljson -bare ca
```
You can then delete the CSR file: `rm ca.csr`
