#!/bin/bash
#cd to script folder
cd $(dirname $0)
#pack
cd ..
pyinstaller ghost.spec
mkdir dist/fluxghost-osx-latest
mv dist/flux_api dist/fluxghost-osx-latest/flux_api
cd dist
zip -r fluxghost-osx-latest.zip fluxghost-osx-latest
mv fluxghost-osx-latest.zip ../../fluxghost-osx-latest.zip
#upload
scp ../../fluxghost-osx-latest.zip 192.168.16.202:/var/www/latest-release/ghost/osx/fluxghost-osx-latest.zip
cd ../tools
