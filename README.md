# sftp-watcher
This simple python script watches any given files for changes and then uploads them to the SFTP/FTP server specified in the `~/.vscode/sftp.json` file.

## Usage
Obviously, install the dependencies
```
pip3 install -r requirements.txt
```

Then the usage of this script is as follows:

```python
python3 main.py <root_directory> <relative_file_paths...>
```

For example:

```python
python3 main.py ~/workspace/my_project src/index.js src/css/styles.css
```

