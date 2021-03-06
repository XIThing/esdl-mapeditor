#  This work is based on original code developed and copyrighted by TNO 2020.
#  Subsequent contributions are licensed to you by the developers of such code and are
#  made available to the Project under one or several contributor license agreements.
#
#  This work is licensed to you under the Apache License, Version 2.0.
#  You may obtain a copy of the license at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Contributors:
#      TNO         - Initial implementation
#  Manager:
#      TNO

from flask import Flask
from flask_socketio import SocketIO
from extensions.settings_storage import SettingsStorage
import src.log as log

logger = log.get_logger(__name__)


MAPEDITOR_SYSTEM_CONFIG = "MAPEDITOR_SYSTEM_CONFIG"
MAPEDITOR_USER_CONFIG = "MAPEDITOR_USER_CONFIG"
MAPEDITOR_UI_SETTINGS = 'ui_settings'

DEFAULT_SYSTEM_SETTING = {
    MAPEDITOR_UI_SETTINGS: {
        'carrier_colors': {}
    }
}

DEFAULT_USER_SETTING = {

}


class MapEditorSettings:
    def __init__(self, flask_app: Flask, socket: SocketIO, settings_storage: SettingsStorage):
        self.flask_app = flask_app
        self.socketio = socket
        self.settings_storage = settings_storage

        self.register()

    def register(self):
        logger.info("Registering MapEditor Settings extension")

        # Assumes the system setting is a list
        @self.socketio.on('mapeditor_system_settings_append_list', namespace='/esdl')
        def mapeditor_system_settings_append_list(info):
            print('mapeditor_system_settings_get:')
            print(info)
            setting_category = info['category']
            setting_name = info['name']
            setting_value = info['value']

            # TODO: figure out a way to replace settings
            sys_set = self.get_system_settings()
            cat = sys_set[setting_category]
            name_list = cat[setting_name]
            name_list.append(setting_value)
            self.set_system_settings(sys_set)
            print(sys_set)

        @self.socketio.on('mapeditor_system_settings_set_dict_value', namespace='/esdl')
        def mapeditor_system_settings_set_dict_value(info):
            setting_category = info['category']
            setting_name = info['name']
            setting_key = info['key']
            setting_value = info['value']

            sys_set = self.get_system_settings()
            cat = sys_set[setting_category]
            name_dict = cat[setting_name]
            name_dict[setting_key] = setting_value
            self.set_system_settings(sys_set)
            print(sys_set)

        @self.socketio.on('mapeditor_system_settings_get', namespace='/esdl')
        def mapeditor_system_settings_get(info):
            print('mapeditor_system_settings_get:')
            print(info)
            setting_category = info['category']
            setting_name = info['name']

            sys_set = self.get_system_settings()
            cat = sys_set[setting_category]
            print(cat[setting_name])
            return cat[setting_name]

    def get_system_settings(self):
        if self.settings_storage.has_system(MAPEDITOR_SYSTEM_CONFIG):
            return self.settings_storage.get_system(MAPEDITOR_SYSTEM_CONFIG)
        else:
            mapeditor_settings = DEFAULT_SYSTEM_SETTING
            self.settings_storage.set_system(MAPEDITOR_SYSTEM_CONFIG, mapeditor_settings)
            return mapeditor_settings

    def set_system_settings(self, settings):
        self.settings_storage.set_system(MAPEDITOR_SYSTEM_CONFIG, settings)

    def get_system_setting(self, name):
        system_settings = self.get_system_settings()
        if name in system_settings:
            return system_settings[name]
        else:
            return None

    def set_system_setting(self, name, value):
        system_settings = self.get_system_settings()
        system_settings[name] = value
        self.set_system_settings(system_settings)

    def get_user_settings(self, user):
        if self.settings_storage.has_user(user, MAPEDITOR_USER_CONFIG):
            return self.settings_storage.get_user(user, MAPEDITOR_USER_CONFIG)
        else:
            user_settings = DEFAULT_USER_SETTING
            self.set_user_settings(user, user_settings)
            return user_settings

    def set_user_settings(self, user, settings):
        self.settings_storage.set_user(user, MAPEDITOR_USER_CONFIG, settings)

    def get_user_setting(self, user, name):
        user_settings = self.get_user_settings(user)
        if name in user_settings:
            return user_settings[name]
        else:
            return None

    def set_user_setting(self, user, name, value):
        user_settings = self.get_user_settings(user)
        user_settings[name] = value
        self.set_user_settings(user, user_settings)