#!/usr/bin/env python
# coding: utf-8
# Copyright (c) 2013-2014 Abram Hindle
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import flask
from flask import Flask, request, redirect
from flask_sockets import Sockets
import gevent
from gevent import queue
import time
import json
import os

app = Flask(__name__)
sockets = Sockets(app)
app.debug = True

clients = []


# from: https://github.com/uofa-cmput404/cmput404-slides/tree/master/examples/WebSocketsExamples
class Client:
    def __init__(self):
        self.queue = queue.Queue()

    def put(self, v):
        self.queue.put_nowait(v)

    def get(self):
        return self.queue.get()


class World:
    def __init__(self):
        self.clear()
        # we've got listeners now!
        self.listeners = list()

    def add_set_listener(self, listener):
        self.listeners.append(listener)

    def update(self, entity, key, value):
        entry = self.space.get(entity, dict())
        entry[key] = value
        self.space[entity] = entry
        self.update_listeners(entity)

    def set(self, entity, data):
        self.space[entity] = data
        self.update_listeners(entity)

    def update_listeners(self, entity):
        '''update the set listeners'''
        for listener in self.listeners:
            listener(entity, self.get(entity))

    def clear(self):
        self.space = dict()

    def get(self, entity):
        return self.space.get(entity, dict())

    def world(self):
        return self.space


def client_propagate(key, val):
    for c in clients:
        c.put(json.dumps({key: val}))


myWorld = World()
myWorld.add_set_listener(client_propagate)


def set_listener(entity, data):
    ''' do something with the update ! '''
    for client in clients:
        json_data = json.dumps({entity: data})
        client.put(json_data)


@app.route('/')
def hello():
    '''Return something coherent here.. perhaps redirect to /static/index.html '''
    return redirect("/static/index.html", code=307)


def read_ws(ws):
    '''A greenlet function that reads from the websocket and updates the world'''
    try:
        while True:
            msg = ws.receive()
            if msg:
                parsed = json.loads(msg)
                print(f"received: {parsed}")
                for k, v in parsed.items():
                    myWorld.set(k, v)
            else:
                break
    except Exception as e:
        print(f"exception occurred while reading ws: {e}\n just trying not to crash at this point :\\")


@sockets.route('/subscribe')
def subscribe_socket(ws):
    '''Fufill the websocket URL of /subscribe, every update notify the
       websocket and read updates from the websocket '''
    client = Client()
    clients.append(client)

    g = gevent.spawn(read_ws, ws)

    ws.send(json.dumps(myWorld.world()))
    try:
        while True:
            # client will wait for an item in the queue to send it
            msg = client.get()
            ws.send(msg)
    except Exception as e:
        print(f"Failed to subscribe{e}")
    finally:
        clients.remove(client)


# I give this to you, this is how you get the raw body/data portion of a post in flask
# this should come with flask but whatever, it's not my project.
def flask_post_json():
    '''Ah the joys of frameworks! They do so much work for you
       that they get in the way of sane operation!'''
    if request.json is not None:
        return request.json
    elif request.data is not None and request.data.decode("utf8") != u'':
        return json.loads(request.data.decode("utf8"))
    else:
        return json.loads(request.form.keys()[0])


@app.route("/entity/<entity>", methods=['POST', 'PUT'])
def update(entity):
    '''update the entities via this interface'''
    data = flask_post_json()

    """
    I'm a little confused why this method allows both POST and PUT, the biggest difference I found between POST and PUT
    is that PUT (should be) idempotent. But in the context of this route (where we have a specific entity ID), I don't 
    see a way to not implement both of them as idempotent.
    """
    original_entity = myWorld.get(entity)
    expected_keys = {"x", "y", "colour"}

    if not all(map(lambda k: k in data.keys(), expected_keys)) and not original_entity:
        return {"message": f"failed to update {entity}: "
                           "there was no pre-existing entity of the world to update,"
                           "and you did not provide all entity fields to create a new one"
                }, 400

    filtered_entity = {k:v for k,v in data.items() if k in expected_keys}
    # ie, filtered_entity will overwrite keys that exist
    replacement_val = {**original_entity, **filtered_entity}
    myWorld.set(entity, replacement_val)

    return replacement_val


@app.route("/world", methods=['POST', 'GET'])
def world():
    '''you should probably return the world here'''
    if request.method == 'GET':
        return myWorld.world()
    elif request.method == 'POST':
        data = flask_post_json()
        for entity in data.keys():
            myWorld.set(entity, data[entity])
        return {"message": "upload world from JSON keys"}


@app.route("/entity/<entity>")
def get_entity(entity):
    '''This is the GET version of the entity interface, return a representation of the entity'''
    return myWorld.get(entity) or {"message": f"no entity {entity} exists"}, 404


@app.route("/clear", methods=['POST', 'GET'])
def clear():
    '''Clear the world out!'''
    myWorld.clear()
    return {"message": "cleared successfully"}


if __name__ == "__main__":
    ''' This doesn't work well anymore:
        pip install gunicorn
        and run
        gunicorn -k flask_sockets.worker sockets:app
    '''
    app.run(port=5002)
