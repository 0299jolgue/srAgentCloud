#!/bin/bash
. "./venv/bin/activate"
cd "./src"
nohup python app.py --name srAgentCloud > nohup.out 2>/dev/null &
cd "../"
deactivate