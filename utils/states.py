"""📌 FSM States"""
from aiogram.fsm.state import State, StatesGroup

class Solve(StatesGroup):
    answering   = State()
    text_answer = State()

class PollSolve(StatesGroup):
    active = State()
    paused = State()

class Create(StatesGroup):
    method     = State()
    polls      = State()
    file       = State()
    poll_time  = State()
    subject    = State()
    title      = State()
    difficulty = State()
    time_limit = State()
    passing    = State()
    attempts   = State()
    visibility = State()

class Admin(StatesGroup):
    broadcast   = State()
    block_user  = State()
    delete_test = State()

class Contact(StatesGroup):
    writing = State()
