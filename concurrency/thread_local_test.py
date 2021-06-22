#!/usr/bin/env python

import threading


class Student:
    def __init__(self, name, age):
        self.name = name
        self.age = age

jack = Student('jack', 20)  # Global object

mydata = threading.local()  # Thread local object

def foo():
    jack.age += 1
    print(f'jack is {jack.age} years old.')

threading.Thread(target=foo).start()
threading.Thread(target=foo).start()

def bar():
    print(f'Current thread name: {mydata.name}')

def baz():
    mydata.name = threading.current_thread().name
    bar()

threading.Thread(target=baz).start()
threading.Thread(target=baz).start()
