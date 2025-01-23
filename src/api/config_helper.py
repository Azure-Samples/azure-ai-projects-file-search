# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE.md file in the project root for full license information.

import configparser
import os

class ConfigHelper:
    
    def __init__(self):
        self.config = configparser.ConfigParser()
        config_file_path = 'config.ini'
        if os.path.exists(config_file_path):
            self.config.read(config_file_path)
        else:
            print(f"Config file {config_file_path} does not exist.")
        
    def get(self, section: str, key: str):
        if self.config.has_option(section, key):
           return self.config.get(section, key)
        return None
            
    def set(self, section, key, value):
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, key, value)
            
    def save(self):
        with open('config.ini', 'w') as configfile:
            self.config.write(configfile)
        
