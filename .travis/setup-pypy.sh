# NOTE: This script needs to be sourced so it can modify the environment.

# Get out of the virtualenv we're in.
deactivate

# Install pyenv.
git clone https://github.com/yyuu/pyenv.git "$HOME/.pyenv"
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"

# Make sure the cache directory exists
# NOTE: pyenv fails to install properly if ~/.pyenv is present, even if the
# directory is empty. So if you cache any directories within ~/.pyenv then you
# will break pyenv.
mkdir -p "${PYTHON_BUILD_CACHE_PATH:-$HOME/.pyenv/cache}"

# Install pypy and make a virtualenv for it.
pyenv install -s pypy-$PYPY_VERSION
pyenv global pypy-$PYPY_VERSION
virtualenv -p $(which python) "$HOME/env-pypy-$PYPY_VERSION"
source "$HOME/env-pypy-$PYPY_VERSION/bin/activate"
