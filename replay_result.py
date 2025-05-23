from datetime import datetime, timedelta, timezone, UTC
import re
import time
import struct
from io import BytesIO
import hashlib

import requests

import prng
from version_config import version_config

class ReplayResultParser:
    def __init__(self, file_path, file_location='local'):
        self.is_genrep = True
        self.file_path = file_path
        self.file_location = file_location

        self.header, self.body = self.get_replay_data()
        
        if self.header is None or self.body is None:
            self.is_genrep = False
            raise ValueError("Invalid file format, not a GENREP file!")

        if self.is_genrep:
            self.valid_msgs = [self.int_to_4byte_le(x)  for x in [27] + list(range(1001, 1097+1))]
            
            ver_str = self.header['version_string']
            if ver_str not in version_config:
                ver_str = 'default'
            self.colors = version_config[ver_str]['colors']
            self.factions = version_config[ver_str]['factions']
            self.factions[-2] = ["Observer", "obs"]

            self.total_colors = len(self.colors)
            self.total_factions = len(self.factions) - 1 # exclude obs

            self.match_data = self.extract_match_data(self.header['game_string'])
            self.replay_player_num = self.match_data['replay_player_num']
            self.players = self.match_data['players']
            self.teams = self.match_data['teams']
            
            # Store players self destruct message indices
            self.player_quit_idxs = self.extract_self_destruct_idxs()

            # Store players first self destruct message index if applicable
            self.update_teams_quit_idxs()

            # Store last crc message indices 
            self.last_crc_idxs, self.last_crc_index, self.last_crc_frame_hex, self.last_crc_hex = self.extract_last_crc_idxs()

            # Find winning team
            self.found_winner, self.winning_team = self.find_winning_team()
            
            # Store player's self destruct frames
            self.players_quit_frames = self.map_quit_frames()

            self.exclude_patterns = [27, 1003, 1001, 1016, 1017, 1018, 1019, 1020, 1021, 1022, 1023, 1024, 1025, 1058, 1075, 1093, 1095, 1097, ]
            self.exclude_patterns = [f"00{self.int_to_4byte_le(x)}0" for x in self.exclude_patterns]

            # Store replay player's final message frame (excluding clear replay data frame)
            self.player_final_message_frame = self.get_player_final_message_frame()

            # Store potential idle/kicked players msg indices
            self.idle_kick_data = {} 
            self.check_for_idle_kicked_players(900, 1800, 1200, 1800, 5)

            self.match_result = ""
            self.winning_team_string = ""

            if len(self.teams) == 1:
                self.found_winner = False
                self.match_result = 'No Result (No opponents)'
                self.winning_team_string = 'No Result (No opponents)'
            elif self.match_data['computer_player_in_game']:
                self.found_winner = False
                self.match_result = 'No Result (No data from computer player)'
                self.winning_team_string = 'Unknown'
            elif (self.header['desync'] == 1 and self.found_winner): #sometimes desync occurs at the end of the game?
                self.winning_team_string = f"{self.winning_team}"
            elif self.header['desync'] == 1:
                self.found_winner = False
                self.match_result = 'No Result (Desync)'
                self.winning_team_string = 'No Result (Desync)'

            self.check_rep = ''
            self.teams_left = 0
            if self.found_winner:
                self.update_match_result()
            if self.match_result == "":
                self.check_ending_and_update()

            self.update_placements()

    def get_new_replay_name(self):
        teams_filename = []
        for team, player in self.teams.items():
            teams_filename_string = ''
            for pl_num in player.keys():
                teams_filename_string += f"{self.players[pl_num]['name']}({self.factions.get(self.players[pl_num]['faction'], ['Unknown', 'Unknown'])[1]}) "
            teams_filename.append(teams_filename_string)

        teams_filename_string = 'vs '.join(teams_filename).strip()
        if len(teams_filename_string) >= 40:
            teams_filename_string = teams_filename_string[:40]

        return self.sanitize_filename(f"{self.rename_ffa_games(self.match_data['match_type'])} ({datetime.fromtimestamp(self.header['begin_timestamp'], UTC).strftime("%y.%m.%d")}) ({self.get_map_name()}) {teams_filename_string}")
   
    def sanitize_filename(self, new_filename, replacement="_"):
        invalid_chars = r'[<>:"/\\|?*]'
        cleaned = re.sub(invalid_chars, replacement, new_filename).strip(" .")
        return cleaned

    def rename_ffa_games(self, match_type):
        teams = match_type.split('v')
        num_teams = len(teams)
        if set(teams) == {'1'} and num_teams > 2:
            return f"ffa{num_teams}"
        elif set(teams) == {'2'} and num_teams > 2:
            return f"t2ffa{num_teams}"
        return match_type

    def get_replay_info_gui(self):
        if self.is_genrep:
            exe_check = "Success" if self.header['exe_crc'] == 3660270360 else "Failed"
            ini_check = "Success" if self.header['ini_crc'] == 4272612339 else "Failed"
            sw_restriction = self.match_data.get('SR', None)
            swr_str = 'Yes' if sw_restriction == '1' else 'No' if sw_restriction == '0' else 'Unknown'
            start_cash = self.match_data.get('SC', 'Unknown')

            replay_info = [
                ("Match ID", self.get_match_id()),
                ("Start Time (UTC+0)", time.strftime("%A, %B %d, %Y at %I:%M %p", time.gmtime(self.header['begin_timestamp']))),
                ("Player Timezone", self.get_offset_systemtime_utc()),
                ("Version String", self.header['version_string']),
                ("Build Date", self.header["build_date"]),
                ("EXE check (1.04)", exe_check),
                ("INI check (1.04)", ini_check),
                ("Map Name", self.get_map_name()),
                ("Start Cash", start_cash),
                ("SW Restriction", swr_str),
                ("Match Type", self.match_data['match_type']),
                ("Replay Duration", self.frames_to_duration(self.match_data['end_frame'])),
                ("Match Mode", self.get_match_mode()),
                ("Player Name", self.players[self.replay_player_num]["name"]),
                # ("Player IP", self.players[self.replay_player_num]["ip"]),
                ("Match Result", self.match_result),
                ("Winning Team", self.winning_team_string),
                ('Color', self.players[self.replay_player_num]['color'])
            ]

            return replay_info

    def get_map_name(self):
        map_name = self.match_data.get('M', 'Unknown')
        return map_name[map_name.rfind('/')+1:] if map_name != 'Unknown' else 'Unknown'

    def round_to_nearest_10(self, n):
        return round(n / 10) * 10

    def format_cash(self, number):
        if number != 'Unknown':
            number = self.round_to_nearest_10(int(number))
        else:
            return ''
        if number >= 1_000_000_000:
            formatted_number = number / 1_000_000_000
            return f"{formatted_number:.1f}".rstrip('0').rstrip('.') + "B"
        elif number >= 1_000_000:
            formatted_number = number / 1_000_000
            return f"{formatted_number:.1f}".rstrip('0').rstrip('.') + "M"
        elif number >= 1_000:
            formatted_number = number / 1_000
            return f"{formatted_number:.1f}".rstrip('0').rstrip('.') + "k"
        else:
            return str(number)

    def get_players_info_gui(self):
        if self.is_genrep:
            player_infos = []
            for player_num, data in self.players.items():
                player_infos.append((data['team'], data['ip'], data['name'], f"{self.factions.get(data['faction'], ['Unknown'])[0]} {'(Random)' if data['faction_randomized']==1 else ''}", self.frames_to_duration(self.players_quit_frames[player_num]['surrender/exit?']), self.frames_to_duration(self.players_quit_frames[player_num]['surrender']), self.frames_to_duration(self.players_quit_frames[player_num]['exit']), self.frames_to_duration(self.players_quit_frames[player_num]['idle/kicked?']), self.players_quit_frames[player_num]['last_crc'] or '', self.ordinal(self.players[player_num].get('placement')), data['color']))
            return player_infos

    def frames_to_duration(self, frames):
        if frames == None:
            return ''
        seconds = frames/30
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)
        int_secs = int(secs)
        frames = int((secs - int_secs) * 30)
        
        if days:
            return f"{int(days):02}:{int(hours):02}:{int(minutes):02}:{int_secs:02}.{frames:02}"
        if hours:
            return f"{int(hours):02}:{int(minutes):02}:{int_secs:02}.{frames:02}"
        if minutes:
            return f"{int(minutes):02}m {int_secs:02}s {frames:02}f"
        return f"{int_secs:02}s {frames:02}f"

    def ordinal(self, n):
        if n==None:
            return ""
        if n == 0:
            return ""
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    def get_match_mode(self):
        host_hex_ip = self.match_data.get('host_hex_ip', 0)
        host_port = self.match_data.get('host_port', 0)

        host_hex_ip_dec = int(host_hex_ip, 16)
        try:
            host_hex_ip_dec = int(host_hex_ip, 16)
        except ValueError:
            return 'Invalid IP'
        
        lan_ranges = [
            ('1A000000', '1AFFFFFF', 'LAN (Radmin)'),
            ('19000000', '19FFFFFF', 'LAN (Hamachi)'),
            ('C0A80000', 'C0A8FFFF', 'LAN'),
            ('0A000000', '0AFFFFFF', 'LAN'),
            ('AC100000', 'AC1FFFFF', 'LAN'),
            ('A9FE0000', 'A9FEFFFF', 'LAN'),
            ('07000000', '07FFFFFF', 'LAN')
        ]
        
        if host_port == '8088':
            for start, end, mode in lan_ranges:
                if int(start, 16) <= host_hex_ip_dec <= int(end, 16):
                    return mode
            return 'GameRanger'
        
        if host_hex_ip_dec == 0 and host_port == '0':
            return 'Skirmish Mode'
        
        return 'Online'

    def string_to_md5(self, input_string):
        return hashlib.md5(input_string.encode()).hexdigest()

    def get_match_id(self):
        """Generate a match id that can be used to uniquely identify all replays of the same game. Useful for those looking 
        to to scrap and merge match info for analysis or a leaderboard.
        """
        # Shatabrick uses the hex of <yyyyddmm><game_sd>, however since the game seed is generated from GetTickCount()
        # there's a risk of collisions. Therefore, based on sample data scrapped from gt for 2 days, perhaps a better way to 
        # generate the match id would be by additionally using the match type, map crc and player names(as long as they are 
        # not corrupt). Player IPs were not used here as there are cases where they are not the same for the same game replay. 

        date_in_replay = datetime.fromtimestamp(self.header['begin_timestamp'], UTC).date()
        game_sd = int(self.match_data['SD'])
        match_type = self.match_data['match_type']
        map_crc = self.match_data['MC']
        player_nicks = self.match_data['player_nicks']
        target_date = date_in_replay
        
        if self.file_location == 'online':
            date_uploaded = self.get_date_from_url()
            if date_uploaded:
                yesterday = date_uploaded - timedelta(days=1)
                two_days_ago = date_uploaded - timedelta(days=2)
                
                # Allow date_in_replay to date back up to 2 days prior to the date_uploaded, else use the date_uploaded.
                target_date = date_in_replay if date_in_replay in (yesterday, two_days_ago) else date_uploaded
    
        return self.string_to_md5(f"{target_date.strftime('%Y%m%d')}{game_sd}{match_type}{map_crc}{''.join(player_nicks)}")
    
    def get_date_from_url(self):
        match = re.search(r'/(\d{4})_(\d{2})_[^/]+/(\d{2})_', self.file_path)
        if match:
            year, month, day = map(int, match.groups())
            return datetime(year, month, day).date()
        else:
            return None

    def fix_start_end_date(self):
        # for online replays, correct the date if the stored date is wrong.
        start_time = self.header['begin_timestamp']
        end_time = self.header['end_timestamp']

        date_in_replay = datetime.fromtimestamp(start_time, UTC).date()
        date_uploaded = self.get_date_from_url()

        if date_uploaded:
            yesterday = date_uploaded - timedelta(days=1)
            two_days_ago = date_uploaded - timedelta(days=2)

            # Allow date_in_replay to date back up to 2 days prior to the date_uploaded, else use the date_uploaded.
            if (date_in_replay == yesterday) or (date_in_replay == two_days_ago):
                return datetime.fromtimestamp(start_time, UTC).strftime("%Y-%m-%d %H:%M:%S"), datetime.fromtimestamp(end_time, UTC).strftime("%Y-%m-%d %H:%M:%S"), f"{date_uploaded}"
            else:
                rep_name = self.file_path.rsplit('/', 1)[1]
                rep_time = rep_name[:8].replace('-', ':')
                dt = datetime.strptime(f"{date_uploaded} {rep_time}", "%Y-%m-%d %H:%M:%S")
                duration_seconds = end_time-start_time
                new_dt = dt + timedelta(seconds=duration_seconds)
                new_end_datetime = new_dt.strftime("%Y-%m-%d %H:%M:%S")

                # return datetime.strptime(f"{date_uploaded} {rep_time}", "%Y-%m-%d %H:%M:%S")
                return f"{date_uploaded} {rep_time}", new_end_datetime, f"{date_uploaded}"
        else:
            return datetime.fromtimestamp(start_time, UTC).strftime("%Y-%m-%d %H:%M:%S"), datetime.fromtimestamp(end_time, UTC).strftime("%Y-%m-%d %H:%M:%S"), f"{date_in_replay}"
    
    def get_offset_systemtime_utc(self):
        systemtime_date = self.header['system_time']
        utc_date = self.header['begin_timestamp']
        
        # Convert Windows SYSTEMTIME to datetime
        year, month, _, day, hour, minute, second, millis = systemtime_date
        windows_dt = datetime(year, month, day, hour, minute, second, millis * 1000).replace(tzinfo=timezone.utc)
        
        utc_dt = datetime.fromtimestamp(utc_date, timezone.utc)
        
        offset_minutes = int((windows_dt - utc_dt).total_seconds() // 60)
        
        sign = '+' if offset_minutes >= 0 else '-'
        hours, minutes = divmod(abs(offset_minutes), 60)
        
        return f"UTC{sign}{hours}" if minutes == 0 else f"UTC{sign}{hours}:{minutes:02}"

    def update_placements(self):
        placement = {}
        if self.found_winner:
            self.match_data['end_frame'] = self.extract_frame(max([quit_idx for team, member in self.teams.items() if team != self.winning_team for quit_idx in member.values()]))
            
            other_teams_rank = sorted(
                [(team, max(player.values())) for team, player in self.teams.items() if team != self.winning_team],
                key=lambda x: x[1], 
                reverse=True
            )
            
            placement = {team: rank for rank, team in enumerate(
                [self.winning_team] + [team for team, _ in other_teams_rank], start=1)}
        elif (len(self.teams) > 2) and (not self.match_data['computer_player_in_game']):
            
            other_teams_rank = sorted(
                [(team, max(player.values())) for team, player in self.teams.items() if -1 not in player.values()],
                key=lambda x: x[1], 
                reverse=True
            )
            
            placement = {team: rank for rank, team in enumerate(
                [team for team, _ in other_teams_rank], start=len(self.teams)-len(other_teams_rank)+1)}

        if placement:
            for player_num, data in self.players.items():
                self.players[player_num]['placement'] = placement.get(data['team'], None)

    def check_ending_and_update(self):
        # Check if game ended without any surrender or exit from all the remaining players. (Based on patterns found in 1v1 games which generalizes to all format?)
        # Pattern 1
        # destroy selected group messages of the remaining players in order once, then logic crc messages of the remaining players in order once.
        # Pattern 2
        # destroy selected group messages of the remaining players in order once, then logic crc messages of the remaining players in order twice.
        # Pattern 3
        # logic crc messages of the remaining players in order once, then destroy selected group messages of the remaining players in order once.
        self.winning_team_string = 'Unknown'
        self.found_winner = False
        
        if self.last_crc_index != -1:
            second_last_crc_index = self.body.rfind(f"470400000{self.replay_player_num:x}0000000200010201", 0, self.last_crc_index)

            last_destroy_selected_msgs_string = ''
            last_logic_crc_msgs_string = ''
            seccond_last_logic_crc_msgs_string = ''

            last_destroy_selected_index = self.body.rfind(f'00eb0300000{self.replay_player_num:x}00000001020101')
            last_destroy_selected_frame = self.body[last_destroy_selected_index-6: last_destroy_selected_index+2]

            for pl in self.players_quit_frames.keys():
                if (self.players_quit_frames[pl]['exit']==None) and (self.players_quit_frames[pl]['surrender/exit?']==None):
                    last_destroy_selected_msgs_string += f'{last_destroy_selected_frame}eb0300000{pl:x}00000001020101'
                    last_logic_crc_msgs_string += f'{self.last_crc_frame_hex}470400000{pl:x}0000000200010201{self.last_crc_hex}00'
                    if second_last_crc_index != -1:
                        second_last_crc_frame = self.body[second_last_crc_index-8:second_last_crc_index]
                        second_last_crc = self.body[second_last_crc_index+26:second_last_crc_index+26+8]
                        seccond_last_logic_crc_msgs_string += f'{second_last_crc_frame}470400000{pl:x}0000000200010201{second_last_crc}00'
                    
            pattern_1 = f'{last_destroy_selected_msgs_string}{last_logic_crc_msgs_string}{self.body[-26:-18]}1b0000000{self.replay_player_num:x}00000000'
            pattern_2 = f'{last_destroy_selected_msgs_string}{seccond_last_logic_crc_msgs_string}{last_logic_crc_msgs_string}{self.body[-26:-18]}1b0000000{self.replay_player_num:x}00000000'
            pattern_3 = f'{last_logic_crc_msgs_string}{last_destroy_selected_msgs_string}{self.body[-26:-18]}1b0000000{self.replay_player_num:x}00000000'

            if self.body.rfind(pattern_1) != -1:
                self.match_result = 'Unknown 1'
            elif self.body.rfind(pattern_2) != -1:
                self.match_result = 'Unknown 2'
            elif self.body.rfind(pattern_3) != -1:
                self.match_result = 'Unknown 3'
        
            if 'Unknown' in self.match_result:
                last_check_frame = 0
                all_crc = re.findall(f'........470400000{self.replay_player_num:x}0000000200010201', self.body)
                if len(all_crc) < 2:
                    last_check_frame = 0
                elif self.match_result!='Unknown 3' and len(all_crc) >= 3:
                    last_check_frame = all_crc[-3][:8]
                else:
                    last_check_frame = all_crc[-2][:8]
                    
                pl_msges = re.findall('00....00000.000000', self.body[self.body.rfind(f"{last_check_frame}470400000"):])
                pl_msges = [s for s in pl_msges if not any(s.startswith(pattern) for pattern in self.exclude_patterns)]
                
                remaining_players = []
                remaining_teams = []
                for x in self.match_data['player_num_list']:
                    if x not in self.player_quit_idxs:    
                        remaining_players.append(x)
                        if self.players[x]['team'] not in remaining_teams:
                            remaining_teams.append(self.players[x]['team'])

                if pl_msges:
                    win_pl = None
                    for msg in reversed(pl_msges):
                        if msg[2:10] in self.valid_msgs:
                            win_pl = int(msg[11:12], 16)
                            if win_pl in self.match_data['player_num_list']:
                                break
                    if (win_pl in self.match_data['player_num_list']) and (len(remaining_teams)==2):
                        self.winning_team = self.players[win_pl]['team']

                        for player, frame in self.players_quit_frames.items():
                            if (player not in self.player_quit_idxs) and (player not in self.match_data['observer_num_list']) and (self.players[player]['team'] != self.winning_team ):
                                if self.hex_to_decimal(self.last_crc_frame_hex) >= 500:
                                    if self.match_result == 'Unknown 2':   
                                        frame['idle/kicked?'] = self.hex_to_decimal(self.last_crc_frame_hex)-300
                                        self.player_quit_idxs[player] = [self.last_crc_index]
                                        self.teams[self.players[player]['team']][player] = self.last_crc_index
                                    else:
                                        frame['idle/kicked?'] = self.hex_to_decimal(self.last_crc_frame_hex)-240
                                        self.player_quit_idxs[player] = [self.last_crc_index]
                                        self.teams[self.players[player]['team']][player] = self.last_crc_index
                        if self.replay_player_num in self.teams[self.winning_team]:
                            self.match_result = f'Win'
                        else:
                            self.match_result = f'Loss'
                        if self.replay_player_num in self.match_data['observer_num_list']:
                            self.match_result = f'Team {self.winning_team} won'
                        self.winning_team_string = f"{self.winning_team}"
                        self.found_winner = True
            else:
                self.match_result = 'Ended with Quit Game in Disconnect Menu'
                if self.replay_player_num in self.match_data['player_num_list']:
                    if (self.replay_player_num in self.player_quit_idxs) and (-1 not in self.teams[self.players[self.replay_player_num]['team']].values()) and (len(self.teams) > 2):
                        self.match_result = 'Loss'
                    elif self.players_quit_frames[self.replay_player_num]['exit'] != None:
                        self.match_result = 'Unk (Not enough data)'
                    if not self.match_data['is_normal_rep']:
                        self.match_result = 'Disconnect (Game aborted or crashed)'
                elif (self.replay_player_num in self.match_data['observer_num_list']) and (self.replay_player_num in self.player_quit_idxs):
                    self.match_result = 'Unk (Not enough data (Obs quit early or before end patterns))'

        else:
            self.match_result = 'Disconnect at start of game'

    def update_match_result(self):
        quit_team, quit_pl_num, game_end_quit_index = max(
            ((team, player, quit_idx) for team, member in self.teams.items() if team != self.winning_team for player, quit_idx in member.items()),
            key=lambda x: x[2])
        idle_kick_idxs = [value['index'] for key, value in self.idle_kick_data.items()]
        self.check_incorrect_winner()
        # if argument of self_destruct msg command is false, means a vote/countdown kick occured.
        # (eg in 1v1 both players replay would declare them as winners if this was not taken into account, 
        # because both would store the other as vote/countdown kicked.)
        if game_end_quit_index not in idle_kick_idxs:
            if int(self.body[game_end_quit_index+22:game_end_quit_index+24], 16) == 0: 
                self.match_result = 'Ended in Disconnect Menue with a player vote/countdown kick'
                self.winning_team_string = 'Unknown'
                self.found_winner = False

        if self.found_winner:
            self.winning_team_string = f"{self.winning_team}"
            # If there is a winning team and the match did not end in DC kick, and if this replay's player stayed till the 
            # end (winner or loser), we can actually detect the situation highlighted in the limitations 
            # (if an exit occured after a last building/sell kick scenario). 
            # Here we flag this game, as this result might not be correct. This is important when merging replay info to correctly 
            # flag games where an inncorrect result might occur.
            
            temp_list = [-1 if quit_idx > game_end_quit_index else quit_idx for quit_idx in self.teams.get(self.winning_team, {}).values()]
            if (game_end_quit_index not in idle_kick_idxs) and (self.replay_player_num not in self.player_quit_idxs) and (self.last_crc_frame_hex) and (self.players_quit_frames[quit_pl_num]['surrender']==None) and (self.match_data['is_normal_rep']) and (self.body.rfind(f"0000000200010201{self.last_crc_hex}00{self.body[-26:-18]}1b0000000{self.replay_player_num:x}00000000") != -1) and (temp_list.count(-1)==1):
                if self.hex_to_decimal(self.last_crc_frame_hex) >= 1000:
                    if self.hex_to_decimal(self.last_crc_frame_hex) - self.extract_frame(game_end_quit_index) <= 200:
                        self.check_rep = ' (Check Result Manually)' # Someone exited after last building/sell kick (the winner? or the loser?)
                        self.check_for_idle_kicked_players(450, 1800, 450, 1800, 1)
                        self.check_incorrect_winner()
                        self.winning_team_string = f"{self.winning_team}"
                
            if self.found_winner:    
                #if found winner, update players match result to win or loss
                if self.replay_player_num in self.match_data['player_num_list']:
                    if self.replay_player_num in self.teams[self.winning_team]:
                        self.match_result = f'Win{self.check_rep}'
                    else:
                        self.match_result = f'Loss{self.check_rep}'                       
                elif self.replay_player_num in self.match_data['observer_num_list']:
                    self.match_result = f'Team {self.winning_team} won{self.check_rep}'
    
    def check_incorrect_winner(self):
        quit_team, quit_pl_num, game_end_quit_index = max(
            ((team, player, quit_idx) for team, member in self.teams.items() if team != self.winning_team for player, quit_idx in member.items()),
            key=lambda x: x[2])
        to_check = [(team, player, quit_idx) for team, member in self.teams.items() if team == self.winning_team for player, quit_idx in member.items()]
        if self.check_rep:    
            if quit_pl_num in self.idle_kick_data:
                self.check_rep = ' (Check Result Manually)'
            else:
                self.check_rep = ' (Check Result Manually) (Correct if loser exited else incorrect)'
        
        if self.players_quit_frames[quit_pl_num]['surrender'] != None:
            self.found_winner = True                
        else:
            for team, player, quit_idx in to_check:
                if (quit_idx > game_end_quit_index) and (self.extract_frame(quit_idx) == self.players_quit_frames[player]['surrender']) and (quit_pl_num in self.idle_kick_data):
                    if self.players_quit_frames[player]['exit'] != None:
                        self.winning_team = quit_team
                        self.found_winner = True
                        self.winning_team_string = f"{self.winning_team}"
                    else:
                        self.winning_team = quit_team
                        self.found_winner = True
                        self.winning_team_string = "Unknown"
                    break

    def is_kick(self, player, kicked_pl_objects):
        ao_patterns = ['......00230400000.000000010301........', '........0f0400000.00000003000103010001................', '........120400000.000000040001030100010301................', '........110400000.00000006000106010101030100010301................................................']
        regex = '|'.join(ao_patterns)
        ao_msgs = re.findall(regex, self.body[:self.idle_kick_data[player]['index']])
        found_count = 0
        found_idxs = []
        for x in reversed(ao_msgs):
            if self.hex_to_decimal(x[-8:]) in kicked_pl_objects:
                if found_count == 2:
                    break
                found_count +=1
                found_idxs.append(self.body.find(x)+8)
        if found_idxs:
            idx = found_idxs[0]
            if len(found_idxs) == 2:
                if self.extract_frame(found_idxs[0])-self.extract_frame(found_idxs[1]) > 4500:
                    idx = found_idxs[1]
                else:
                    idx = found_idxs[0]
            if self.extract_frame(self.idle_kick_data[player]['index']) - self.extract_frame(idx) <= 300:
                return True
            else:
                return False
        return False

    def get_closest_kick_frame(self, player, clicked):
        # self.idle_kick_data[player]['update'] = False
        csg_msgs = re.findall(f'00e90300000{player:x}000000020201030101'+r'(.{8})', self.body)
        counts = {}
        for fr in csg_msgs:
            if fr in counts:
                counts[fr] += 1
            else:
                counts[fr] = 1
        kicked_pl_objects = []
        for fr, count in counts.items():
            if count>= clicked:
                kicked_pl_objects.append(self.hex_to_decimal(fr))

        ao_patterns = ['......00230400000.000000010301........', '........0f0400000.00000003000103010001................', '........120400000.000000040001030100010301................', '........110400000.00000006000106010101030100010301................................................']
        regex = '|'.join(ao_patterns)
        ao_msgs = re.findall(regex, self.body[self.idle_kick_data[player]['index']:])
        found_count = 0
        found_idxs = []
        for x in reversed(ao_msgs):
            if self.hex_to_decimal(x[-8:]) in kicked_pl_objects:
                if found_count == 2:
                    break
                found_count +=1
                found_idxs.append(self.body.find(x)+8)
        if found_idxs:
            idx = found_idxs[0]
            if len(found_idxs) == 2:
                if self.extract_frame(found_idxs[0])-self.extract_frame(found_idxs[1]) > 4500:
                    idx = found_idxs[1]
                else:
                    idx = found_idxs[0]
            if (len(self.player_quit_idxs[player]) == 2) and (self.players_quit_frames[player]['surrender'] == None) and ((self.players_quit_frames[player]['exit'] != None) or (self.players_quit_frames[player]['surrender/exit?'] != None)):
                if idx < self.player_quit_idxs[player][1]:
                    self.idle_kick_data[player]['frame'] = self.extract_frame(idx)
                    self.idle_kick_data[player]['index'] = idx
                    self.player_quit_idxs[player][0] = idx
            elif (len(self.player_quit_idxs[player]) == 1) and (self.players_quit_frames[player]['surrender'] == None) and ((self.players_quit_frames[player]['exit'] != None) or (self.players_quit_frames[player]['surrender/exit?'] != None)):
                if idx < self.player_quit_idxs[player][0]:
                    self.idle_kick_data[player]['frame'] = self.extract_frame(idx)
                    self.idle_kick_data[player]['index'] = idx
                    self.player_quit_idxs[player][0] = idx
            elif (self.players_quit_frames[player]['surrender'] == None) and (self.players_quit_frames[player]['exit'] == None) and (self.players_quit_frames[player]['surrender/exit?'] == None):
                self.idle_kick_data[player]['frame'] = self.extract_frame(idx)
                self.idle_kick_data[player]['index'] = idx
                self.player_quit_idxs[player][0] = idx
        
        if self.extract_frame(self.last_crc_index) - self.extract_frame(self.idle_kick_data[player]['index']) <= 600:
            if not self.is_kick(player, kicked_pl_objects) and (clicked < 5):
                if len(self.player_quit_idxs[player]) == 1:
                    del self.player_quit_idxs[player]
                else:
                    del self.player_quit_idxs[player][0]
                self.players_quit_frames[player]['idle/kicked?'] = None
                del self.idle_kick_data[player]

    def check_for_idle_kicked_players(self, diff1, diff2, diff3, diff4, clicked):
        update_again = False
        if self.player_final_message_frame >= 5400: # if replay is greater than 3 minutes
            for player, frame in self.players_quit_frames.items():
                if (player not in self.match_data['observer_num_list']) and ((frame['surrender'] == None) or (player not in self.player_quit_idxs)) and (player not in self.idle_kick_data):    
                    pl_msges = re.findall(f'00....00000{player:x}000000', self.body)
                    pl_msges = [s for s in pl_msges if not any(s.startswith(pattern) for pattern in self.exclude_patterns)]
                    if len(pl_msges) >=1:
                        for msg in reversed(pl_msges):
                            if (int(msg[11:12], 16) == player) and (msg[2:10] in self.valid_msgs):
                                msg_index = self.body.rfind(msg)
                                msg_frame = self.extract_frame(msg_index+2)
                                if msg_frame <= self.player_final_message_frame:
                                    if self.found_winner:
                                        diff = diff1
                                    else:
                                        diff = diff2
                                    if (self.player_final_message_frame - msg_frame) >= diff1:
                                        if (frame['exit'] != None) and ((frame['exit'] - msg_frame) >= diff3):
                                            frame['idle/kicked?'] = msg_frame
                                            self.player_quit_idxs[player].insert(0, msg_index+2)
                                            update_again = True
                                            if player not in self.idle_kick_data:
                                                self.idle_kick_data.setdefault(player, {})['index'] = msg_index+2
                                            self.get_closest_kick_frame(player, clicked)
                                        elif (frame['surrender/exit?'] != None) and ((frame['surrender/exit?'] - msg_frame) >= diff4):
                                            frame['idle/kicked?'] = msg_frame
                                            self.player_quit_idxs[player].insert(0, msg_index+2)
                                            update_again = True
                                            if player not in self.idle_kick_data:
                                                self.idle_kick_data.setdefault(player, {})['index'] = msg_index+2
                                            self.get_closest_kick_frame(player, clicked)
                                        elif (player not in self.player_quit_idxs) and (self.player_final_message_frame - msg_frame >= diff):
                                            frame['idle/kicked?'] = msg_frame
                                            self.player_quit_idxs[player] = [msg_index+2]
                                            update_again = True
                                            if player not in self.idle_kick_data:
                                                self.idle_kick_data.setdefault(player, {})['index'] = msg_index+2
                                            self.get_closest_kick_frame(player, clicked)
                                    break
        
        if update_again:
            for player, frame in self.players_quit_frames.items():
                if frame['idle/kicked?'] != None:
                    if 'frame' in self.idle_kick_data[player]:
                        frame['idle/kicked?'] = self.idle_kick_data[player]['frame']
                    if frame['surrender/exit?'] != None:
                        frame['exit'] = frame['surrender/exit?']
                        frame['surrender/exit?'] = None
            self.update_teams_quit_idxs()
            self.found_winner, self.winning_team = self.find_winning_team()
            
            if self.found_winner and len(self.teams)>1:
                victory_idx = max([quit_idx for team, member in self.teams.items() if team != self.winning_team for quit_idx in member.values()])
                for pl_num, quit_idx in self.teams[self.winning_team].items():
                    if (quit_idx != -1) and (self.players_quit_frames[pl_num]['surrender/exit?'] != None) and (self.players_quit_frames[pl_num]['surrender/exit?'] > self.extract_frame(victory_idx)):
                        self.players_quit_frames[pl_num]['exit'] = self.players_quit_frames[pl_num]['surrender/exit?']
                        self.players_quit_frames[pl_num]['surrender/exit?'] = None

    def get_player_final_message_frame(self):
        player_final_message_frame = self.match_data['end_frame']
        replay_player_data = self.players_quit_frames[self.replay_player_num]
        if self.replay_player_num in self.player_quit_idxs:
            if len(self.player_quit_idxs[self.replay_player_num]) == 1:
                if replay_player_data['surrender'] == None:
                    if replay_player_data['exit'] != None:
                        player_final_message_frame = replay_player_data['exit']
                    elif replay_player_data['surrender/exit?'] != None:
                        player_final_message_frame = replay_player_data['surrender/exit?']
                else:
                    if self.last_crc_index != -1: 
                        player_final_message_frame = self.extract_frame(self.last_crc_index)
            else:
                player_final_message_frame = replay_player_data['exit']
        else:
            if self.last_crc_index != -1:
                player_final_message_frame = self.extract_frame(self.last_crc_index)
        return player_final_message_frame
    
    def extract_frame(self, index):
        """Extract frame value at given message index in replay."""
        return self.hex_to_decimal(self.body[index-8:index])

    def extract_crc(self, index):
        """Extract CRC value at given crc message index in replay."""
        return self.hex_to_decimal(self.body[index+34:index+44])

    def map_quit_frames(self):
        players_quit_frames = {player: {
            'surrender': None,
            'exit': None,
            'last_crc': None,
            'surrender/exit?': None,
            'idle/kicked?': None
        } for player in self.players}

        # Cache self destruct msg index where victory occurs if it exists
        if self.found_winner and len(self.teams)>1:
            victory_idx = max([quit_idx for team, member in self.teams.items() if team != self.winning_team for quit_idx in member.values()])

        for player_num in players_quit_frames:
            player_data = players_quit_frames[player_num]
            
            # Add CRC data if available and applicable
            if player_num in self.last_crc_idxs:
                # Check if we should add CRC
                crc_condition = ((player_num not in self.player_quit_idxs and self.replay_player_num not in self.player_quit_idxs) or 
                                (player_num in self.player_quit_idxs and len(self.player_quit_idxs[player_num])==1 and self.last_crc_index > self.player_quit_idxs[player_num][0]
                                    and (self.replay_player_num not in self.player_quit_idxs or self.last_crc_index > self.player_quit_idxs[self.replay_player_num][0]) ) or
                                (player_num not in self.player_quit_idxs and self.replay_player_num in self.player_quit_idxs and self.last_crc_index > self.player_quit_idxs[self.replay_player_num][0]))
                                
                if crc_condition:
                    player_data['last_crc'] = self.extract_crc(self.last_crc_idxs[player_num])
        
        for player_num in players_quit_frames:  
            player_data = players_quit_frames[player_num]  
            
            # Skip players without quit data
            if player_num not in self.player_quit_idxs:
                continue
                
            quit_indices = self.player_quit_idxs[player_num]
            
            # Handle multiple quit events (always surrender then exit)
            if len(quit_indices) > 1:
                player_data['surrender'] = self.extract_frame(quit_indices[0])
                player_data['exit'] = self.extract_frame(quit_indices[1])
                continue
                
            # Handle single quit event
            frame_time = self.extract_frame(quit_indices[0])
            
            # Observer can only exit
            if player_num in self.match_data['observer_num_list']:
                player_data['exit'] = frame_time
                continue
                
            # Players that surrender only still continue sending logic crc checks.
            if player_num in self.last_crc_idxs and self.last_crc_index > quit_indices[0]:
                if frame_time == self.extract_frame(self.last_crc_index):
                    # if player surrenders/exits at the same time a logic crc check was done.
                    player_data['surrender/exit?'] = frame_time 
                else:
                    player_data['surrender'] = frame_time
                continue
                
            # Special handling for comparing to this replay_player_num
            if player_num != self.replay_player_num and self.replay_player_num in self.player_quit_idxs:

                # Winning players at the end can only exit
                if (self.found_winner) and (player_num in self.teams[self.winning_team]) and len(self.teams)>1:
                    if quit_indices[0] > victory_idx:
                        player_data['exit'] = frame_time
                        continue

                # Exit if player was not found in crc check
                if players_quit_frames[self.replay_player_num]['last_crc'] == None:
                    crc_index_after_quit = self.body.find(f"470400000{self.replay_player_num:x}0000000200010201", self.player_quit_idxs[player_num][0])
                    if crc_index_after_quit != -1:
                        crc_frame_after_quit = self.body[crc_index_after_quit-8:crc_index_after_quit]
                        pl_num_check = self.body.find(f"{crc_frame_after_quit}470400000{player_num:x}0000000200010201", self.player_quit_idxs[player_num][0])
                        if (pl_num_check != -1):
                            player_data['surrender'] = frame_time
                        else:
                            player_data['exit'] = frame_time
                    else:
                        player_data['surrender/exit?'] = frame_time
                elif players_quit_frames[self.replay_player_num]['last_crc'] != None:
                    if player_data['last_crc'] == None:
                        player_data['exit'] = frame_time
                    else:
                        player_data['surrender'] = frame_time
                continue
                
            player_data['exit'] = frame_time
        return players_quit_frames

    def find_winning_team(self):
        teams_remain = []
        teams_quit = []
        for team, members in self.teams.items():
            if -1 in members.values():
                if teams_remain:
                    return False, None
                teams_remain.append(team)
            else:
                teams_quit.append((team, max(members.values())))
        if teams_remain:
            return True, teams_remain[0]
        else:
            if teams_quit:
                return True, max(teams_quit, key=lambda x: x[1])[0]
            else:
                return False, None

    def extract_last_crc_idxs(self):
        last_crc_data = {}
        last_crc_index = self.body.rfind(f"470400000{self.replay_player_num:x}0000000200010201")
        last_crc_frame = 0
        last_crc = 0
        if last_crc_index != -1:
            last_crc_frame = self.body[last_crc_index-8:last_crc_index]
            last_crc = self.body[last_crc_index+26:last_crc_index+26+8]
            for match in re.finditer(f'{last_crc_frame}470400000.0000000200010201', self.body):
                match_str = int(match.group(0)[17:18], 16)
                last_crc_data[match_str] = match.start()
        return last_crc_data, last_crc_index, last_crc_frame, last_crc

    def extract_self_destruct_idxs(self):
        quit_data = {}
        for match in re.finditer(r'450400000.000000010201', self.body):
            match_str = int(match.group(0)[9:10], 16)
            if match_str in quit_data:
                quit_data[match_str].append(match.start())
            else:
                quit_data[match_str] = [match.start()]
        return quit_data

    def update_teams_quit_idxs(self):
        for team in self.teams:
            for player in self.teams[team]:
                if player in self.player_quit_idxs:
                    self.teams[team][player] = self.player_quit_idxs[player][0]

    def read_null_terminated_string(self, data, encoding='utf-8', return_is_corrupt=False):
        chars = []
        null_char = b'\x00' if encoding != 'utf-16' else b'\x00\x00'

        while True:
            char = data.read(2 if encoding == 'utf-16' else 1)
            if not char or char == null_char:
                break
            chars.append(char)

        byte_data = b''.join(chars)
        is_corrupt = encoding == 'utf-8' and self.check_encoding_bytes(byte_data)

        try:
            result = byte_data.decode(encoding)
        except:
            try:
                result = byte_data.decode('cp1252')
            except:
                result = byte_data.decode('latin-1')

        return (result, is_corrupt) if return_is_corrupt else result

    def check_encoding_bytes(self, input_bytes):
        try:
            decoded_content = input_bytes.decode('utf-8')
            encoded_bytes = decoded_content.encode('utf-8')
            if input_bytes != encoded_bytes:
                return True
            else:
                return False
        except UnicodeDecodeError:
            return True
        except Exception as e:
            print(f"Error occurred: {e}")
            return None

    def is_valid_utf8(self, byte_string):
        try:
            byte_string.decode('utf-8')
            return True
        except UnicodeDecodeError:
            return False

    def get_replay_data(self):
        header = {}
        body = ''
        if self.file_location=='local':
            with open(self.file_path, 'rb') as file_handle:
                header, body = self.parse_replay_data(file_handle)
        elif self.file_location=='online':
            try:
                response = requests.get(self.file_path)
                response.raise_for_status()
                with BytesIO(response.content) as file_handle:
                    header, body = self.parse_replay_data(file_handle)
            except requests.exceptions.RequestException as e:
                print(f"An error occurred: {e}") 
        
        return header, body

    def parse_replay_data(self, file_handle):
        """Well, actually just parse the header and return it along with the rest of the body."""
        magic = file_handle.read(6)
        if magic != b'GENREP':
            return None, None
        begin_timestamp, end_timestamp, total_frames = struct.unpack('<III', file_handle.read(12))
        desync, early_quit = struct.unpack('<BB', file_handle.read(2))
        disconnect = struct.unpack('<8B', file_handle.read(8))
        file_name = self.read_null_terminated_string(file_handle, encoding='utf-16')
        system_time = struct.unpack('<8H', file_handle.read(16))
        version_string = self.read_null_terminated_string(file_handle, encoding='utf-16')
        build_date = self.read_null_terminated_string(file_handle,encoding='utf-16')
        version_minor, version_major = struct.unpack('<HH', file_handle.read(4))
        exe_crc, ini_crc = struct.unpack('<II', file_handle.read(8))
        game_string, is_corrupt  = self.read_null_terminated_string(file_handle, return_is_corrupt=True)
        local_player_index = self.read_null_terminated_string(file_handle)
        difficulty, original_game_mode, rank_points, max_fps = struct.unpack('<iiii', file_handle.read(16))
        data = file_handle.read().hex()

        header =  {
            "magic": magic,
            "begin_timestamp": begin_timestamp,
            "end_timestamp": end_timestamp,
            "total_frames": total_frames,
            "desync": desync,
            "early_quit": early_quit,
            "disconnect": disconnect,
            "file_name": file_name,
            "system_time": system_time,
            "version_string": version_string,
            "build_date": build_date,
            "version_minor": version_minor,
            "version_major": version_major,
            "exe_crc": exe_crc,
            "ini_crc": ini_crc,
            "game_string": game_string,
            "local_player_index": int(local_player_index),
            "difficulty": difficulty,
            "original_game_mode": original_game_mode,
            "rank_points": rank_points,
            "max_fps": max_fps,
            "is_corrupt": is_corrupt,
        }

        return header, data

    def hex_to_decimal(self, hex_string):
        int_value = int.from_bytes(bytes.fromhex(hex_string), byteorder='little')
        return int_value

    def int_to_4byte_le(self, number):
      """Converts an integer to a 4-byte little-endian hex string."""
      return struct.pack("<I", number).hex()

    def fix_empty_slot_issue(self, slot_data):
        initial_indices = {}
        occupied_idx = 0
        for i, slot in enumerate(slot_data):
            if slot not in {'X', 'O'}:
                initial_indices[i] = occupied_idx
                occupied_idx += 1
        return initial_indices

    def get_pl_num_offset(self, player_slot, slot_data):
        """Player num usually starts at 2, however for some maps this is not the case (eg. casino maps), we assume
        that the slot number will tell us this replay's player. If the replay ended properly then we could use the
        final message and slot number to get the offset. However, if the slot number is wrong or is manipulated/corrupt?, 
        we would get wrong offset values, so well shall first look for the player number using the first logic crc
        check, and then use other methods if that fails"""
        fixed_slots = self.fix_empty_slot_issue(slot_data)
        offset = 2
        pl_num_from_first_crc = []
        index_of_first_crc = self.body.find("00470400000")
        if index_of_first_crc != -1:
            frame_hex = self.body[index_of_first_crc-6:index_of_first_crc+2]
            frame_first_crc = self.hex_to_decimal(frame_hex)
            first_check = set(re.findall(f"{frame_hex}470400000.", self.body))
            
            if first_check and len(first_check)>1:
                for ck in sorted(first_check):
                    pl_num_from_first_crc.append(int(ck[-1], 16))
            if len(pl_num_from_first_crc) == len(fixed_slots):
                offset = pl_num_from_first_crc[0]
                replay_player_num = offset + fixed_slots[player_slot]
                
                if self.body[-18:-10] == '1b000000':
                    if replay_player_num != int(self.body[-9:-8], 16):
                        # print('Wrong slot in rep.')
                        # since there are cases where slot is wrong, take the replay_player_num from the clear replay message at the end.
                        replay_player_num = int(self.body[-9:-8], 16)
                    if offset < 2:
                        offset = 2
                    return replay_player_num, offset, True
                else:
                    return replay_player_num, offset, False
        
        if pl_num_from_first_crc:
            offset = pl_num_from_first_crc[0]
            if self.body[-18:-10] == '1b000000':
                replay_player_num = int(self.body[-9:-8], 16)
                offset = replay_player_num - fixed_slots[player_slot]
                if offset < 2:
                    offset = 2
                return replay_player_num, offset, True

        # if no logic crc was found, the replay ended in dc at start, so it dosen't matter.  
        replay_player_num = offset + fixed_slots[player_slot]
        if self.body[-18:-10] == '1b000000':
            return replay_player_num, offset, True
        else:
            return replay_player_num, offset, False

    def comp_name(self, comp):
        if comp == 'E':
            return 'Easy AI'
        elif comp == 'M':
            return 'Medi AI'
        elif comp == 'H':
            return 'Hard AI'

    def parse_slot_data(self, match_data):
        players = match_data['players'] = {}
        teams = match_data['teams'] = {}
        match_data['computer_player_in_game'] = False
        player_num_list = match_data['player_num_list'] = []
        observer_num_list = match_data['observer_num_list'] = []
        player_nicks = match_data['player_nicks'] = []
        offset = match_data['player_num_offset']

        pl_count = 0
        for index, player_raw in enumerate(match_data['S']):
            if (player_raw == 'X') or (player_raw == 'O'):
                continue
            player_data = player_raw.split(',')
            if player_data[0][0] == 'H':
                if index == 0:
                    match_data['host_hex_ip'] = player_data[1]
                    match_data['host_port'] = player_data[2]
                players[pl_count+offset] = {
                    'type': 'human',
                    'name': player_data[0][1:],
                    'ip': player_data[1],
                    # 'port': int(player_data[2]),
                    # 'is_accepted': player_data[3][0],
                    # 'has_map': player_data[3][1],
                    'color': int(player_data[4]),
                    'faction': int(player_data[5]),
                    # 'start_pos': int(player_data[6]),
                    'team': int(player_data[7])+1,
                    # 'nat_behavior': int(player_data[8]),
                    # 'dc': disconnect[index],
                    'faction_randomized': 0,
                    'placement': None,
                }

                pl_nick = player_data[0][1:]
                if self.header['is_corrupt']:
                    try:
                        if not self.is_valid_utf8(pl_nick.encode('latin-1')):
                            pl_nick = 'player'
                    except:
                        pl_nick = 'player'
                player_nicks.append(pl_nick)

                players[pl_count+offset]['faction_randomized'] = 1 if players[pl_count+offset]['faction'] == -1 else 0
                
                if int(player_data[5]) != -2:
                    if (int(player_data[7])+1) not in teams:
                        teams[int(player_data[7])+1] = {}
                    teams[int(player_data[7])+1][pl_count+offset] = -1
                    player_num_list.append(pl_count+offset)
                else:
                    observer_num_list.append(pl_count+offset)
                pl_count += 1

            elif player_data[0][0] == 'C':
                match_data['computer_player_in_game'] = True
                player_num_list.append(pl_count+offset)
                players[pl_count+offset] = {
                    'type': 'computer',
                    'name': self.comp_name(player_data[0][1:]),
                    'ip': '',
                    # 'port': '',
                    # 'is_accepted': '',
                    # 'has_map': '',
                    'color': int(player_data[1]),
                    'faction': int(player_data[2]),
                    # 'start_pos': int(player_data[3]),
                    'team': int(player_data[4])+1,
                    # 'nat_behavior': '',
                    # 'dc': disconnect[index],
                    'faction_randomized': 0,
                    'placement': None,
                }
                player_nicks.append(self.comp_name(player_data[0][1:]))
                players[pl_count+offset]['faction_randomized'] = 1 if players[pl_count+offset]['faction'] == -1 else 0
                
                if int(player_data[2]) != -2:
                    if (int(player_data[4])+1) not in teams:
                        teams[int(player_data[4])+1] = {}
                    teams[int(player_data[4])+1][pl_count+offset] = -1
                # else:
                #     observer_num_list.append(pl_count+offset)
                pl_count += 1

    def extract_match_data(self, game_string):
        match_data = {}
        parts = game_string[:-2].split(';')

        parts_list = []
        rest_of_string = ""

        # Usually players cant use ';' in their name, but we still handle it here, just incase.
        for part in parts:
            if part.startswith('S=H'):
                # Once we encounter "S=H", collect the rest of the string
                rest_of_string = ';'.join(parts[parts.index(part):])
                break
            parts_list.append(part)

        parts_list.append(rest_of_string)

        for part in parts_list:
            key_value = part.split('=', maxsplit=1)
            if len(key_value) == 2:
                key, value = key_value
                match_data[key] = value

        # Usually players cant use ':' in their name, but we still handle it here, just incase.
        slot_data = re.split(r':(?=[HCXO])', match_data.get('S', ''))
        if match_data.get('S'):
            match_data['S'] = slot_data
        match_data['replay_player_num'], match_data['player_num_offset'], match_data['is_normal_rep'] = self.get_pl_num_offset(self.header['local_player_index'], match_data['S'])
        match_data['end_frame'] = self.header['total_frames']
        if not match_data['is_normal_rep']:
            last_messages = re.findall(r"00....00000.0000000", self.body[-10000:])
            if len(last_messages) >= 1:
                for msg in reversed(last_messages):
                    if msg[2:10] in self.valid_msgs:
                        index = self.body.rfind(msg)
                        match_data['end_frame'] = self.hex_to_decimal(self.body[index-6:index+2])
                        break

        self.parse_slot_data(match_data)
        self.assign_random_faction_color(match_data)

        self.fix_teams(match_data['teams'], match_data['players'])
        match_data['match_type'] = self.get_match_type(match_data['teams'])

        return match_data

    def assign_random_faction(self, game_prng, game_sd):
        discard = game_sd % 7
        for _ in range(discard):
            game_prng.get_value(0, 1)  # Discard values to improve randomness

        faction_index = game_prng.get_value(0, 1000) % self.total_factions
        return faction_index

    def assign_random_color(self, game_prng, taken_colors):
        color_index = -1
        while color_index == -1:
            random_color = game_prng.get_value(0, self.total_colors - 1)
            if not taken_colors[random_color]:
                color_index = random_color
                taken_colors[random_color] = True
        return color_index

    def assign_random_faction_color(self, match_data):
        game_sd = int(match_data['SD'])
        game_prng = prng.RandomGenerator(game_sd)

        if (not match_data.get('SR')) and (not match_data.get('SC')):
            # probably a generals replay.
            self.total_factions = 3

        taken_colors = [False]*self.total_colors
        for key, value in match_data['players'].items():
            if (value['color'] != -1) and (value['color'] < self.total_colors):
                taken_colors[value['color']] = True

        for key, value in match_data['players'].items():
            if value['faction'] == -1:
                faction_index = self.assign_random_faction(game_prng, game_sd)
                value['faction'] = faction_index
            elif value['faction'] > 0:
                value['faction'] = value['faction']-2
            if value['color'] == -1:
                color_index = self.assign_random_color(game_prng, taken_colors)
                value['color'] = color_index

    def fix_teams(self, teams, players):
        if 0 in teams:
            taken_keys = set(teams.keys())
            new_team_keys = [key for key in range(1, 9) if key not in taken_keys]
            players_without_team = teams.pop(0)
            for player, quit_idx in players_without_team.items():
                new_team_key = new_team_keys.pop(0)
                teams[new_team_key] = {player: quit_idx}
                players[player]['team'] = new_team_key
        # sorted_d = dict(sorted(teams.items()))
        # teams.clear()
        # teams.update(sorted_d)

    def get_match_type(self, teams):
        match_type = 'v'.join(map(str, sorted(len(players) for players in teams.values())))
        return match_type
