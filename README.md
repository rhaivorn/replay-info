# Replay Info 1.1.0

## Overview
A simple gui application that allows Generals Zero Hour players to easily view replay information from local replay files as well as replays stored in Gentool.

## Key Features

- **Replay Metadata and Result Information**  
  View information of replays stored both locally and online, including player factions, match results, and other game metadata.

- **Batch Replay Renaming**  
  Automatically rename local replay files in bulk for easy identification.

- **Gentool Multi-Directory Replay Browsing**  
  Access replay data from **multiple** gentool directories covering the last **70 days**.  
  Users can select a custom date range within this window. Player directories from the past 70 days are stored in a database for faster and more efficient searching.

- **Fast Batch Replay Downloads**  
  Efficiently download large batches of online replays from **multiple** player directories covering the past 70 days.

## Installation

### Prerequisites
Ensure you have Python installed. You can download it from [python.org](https://www.python.org/downloads/).

### Clone the Repository
```sh
git clone https://github.com/rhaivorn/replay-info.git
cd replay-info
```

### Install Dependencies
```sh
pip install -r requirements.txt
```

## Usage
Run the application using:
```sh
python main.py
```

## Limitations
Game results are only possible because the replay recorder stores the 'self_destruct' message(order) when a player clicks on Surrender, Exit Game, or is kicked via dc vote/countdown. As a result, any game involving a player who gets kicked due to losing their last building or selling it may lead to incorrect results.

If this scenario occurs early in the game, the game result is often still correct if the player exits shortly after being kicked, or by detecting if the player was idle during the remaining part of the game to obtain the closest frame where the kick occured. However, if this occurs near the end of the game, at the point when victory is decided, it can lead to incorrect results — particularly if the winning player exits right away. (This scenario can be detected in replays where the player stayed till the end screen without exiting.)

Therefore, in such situations, it is recommended that the remaining player(s) stay in the game until it fully ends and continue issuing commands (such as creating units or constructing buildings) in the short period after kicking the opponent and before the victory screen to ensure the game result can be determined accurately.

These limitations are likely to be resolved in the future community patch of the game.


## Feedback
Have questions, feedback, inquiries/issues? Feel free to reach out on Discord:  **rhaivorn**
