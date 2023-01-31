# sigsci-module-python
Signal Sciences WSGI python middleware

# Build artifacts
```shell
make build
```

# Install via pip

### Python 3
```shell
pip3 install sigscimodule-1.4.1.tar.gz
```

### Python 2
```shell
pip install sigscimodule-1.4.1.tar.gz
```

# Usage
### In the setup.py file of your Flask application, add the following line to reference the sigscimodule package:
```shell
packages = ['flask', '......', 'sigscimodule']
```

### In the app.py file of your application, add the following line to import the import the sigscimodule middleware:
```shell

from sigscimodule import Middleware
```

### Below the from sigscimodule import Middleware line, wrap the application object to apply the sigscimodule middleware:
```shell
app.wsgi_app = Middleware(app.wsgi_app)
```
