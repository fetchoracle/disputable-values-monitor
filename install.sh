#!/bin/bash

rm -r ./build
rm -r ./lib
rm -r ./venv

git submodule update --init --recursive
git submodule update --remote --recursive

# git submodule foreach git submodule update

python3.9 -m venv venv

source venv/bin/activate

pip install .
pip install -r requirements.txt

python -c "import telliot_core; print(f'telliot-core version installed - {telliot_core.__version__}')"
python -c "import telliot_feeds; print(f'telliot-feeds version installed - {telliot_feeds.__version__}')"