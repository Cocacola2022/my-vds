#!/bin/bash

python3 play1.py &
echo 'Запущен VK'

python3 bot_kostya.py &
echo 'Запущен мой TG'

python3 bot_danilka.py &
echo 'Запущен Данилка TG'
