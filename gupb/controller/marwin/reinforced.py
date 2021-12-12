import random

import numpy as np

from gupb.model import arenas
from gupb.model import characters
from gupb.model.coordinates import Coords
from gupb.controller.random import POSSIBLE_ACTIONS

from gupb.controller.marwin.base import BaseMarwinController
import gupb.controller.marwin.utils as utils

class ReinforcedMarwin(BaseMarwinController):
	TURNAROUND_LIMIT = 3
	EPS = 0.15

	def __init__(self, name):
		super(ReinforcedMarwin, self).__init__(name)
		self.policies = {"StandGround": self.standGroundPolicy, "Arm": self.armYourselfOrAttackfPolicy, }
#"Order66": ExecuteOrder66Politics}
		# initially all politics are of the same worth and are used 0 times
		self.Q = {pol: 1 for pol in self.policies.keys()}
		self.N = {pol: 0 for pol in self.policies.keys()}
		self.current_policy = random.choice(self.policies) if random.uniform(0, 1) < ReinforcedMarwin.EPS else \
			max(self.Q.items(), key= lambda it: it[1])[0]
		self._arena = np.zeros(utils.ARENA_SIZE, dtype=int)
		self.weapons_to_take = None

		self._arena_description = None
		self._arena = None
		self._menhir_coords = None
		self._current_path = None
		self._next_move = None
		self._current_state = utils.TURN_AROUND
		self._turnaround_turns = 0
		self._last_action = characters.Action.DO_NOTHING
		self._current_weapon = None
		self._last_position = None
		self._found_turns = set()
		self._previously_found_turns = set()
		self._dead_ends = set()
		self._i = 0

	def reset(self, arena_description: arenas.ArenaDescription) -> None:
		if self._current_path is not None:
			self._current_path.clear()
		self._arena_description = arena_description
		self._found_turns.clear()
		self._previously_found_turns.clear()
		self._dead_ends.clear()

		self._menhir_coords = None
		self._current_path = None
		self._arena = np.zeros(utils.ARENA_SIZE, dtype=int)
		self._current_state = utils.TURN_AROUND
		self._next_move = None
		self._turnaround_turns = 0
		self._last_action = characters.Action.DO_NOTHING
		self._current_weapon = None
		self._last_position = None
		self._i = 0

	def decide(self, knowledge: characters.ChampionKnowledge) -> characters.Action:
		return self.policies[self.current_policy](knowledge)

	def praise(self, score: int) -> None:
		self.N[self.current_policy] += 1
		n = self.N[self.current_policy]
		q = self.Q[self.current_policy]
		self.Q[self.current_policy] += (1 / n * (score - q))

	def _init_round(self, knowledge):
		my_position = knowledge.position
		my_character = self._get_champion(knowledge)
		action = characters.Action.DO_NOTHING
		current_facing = my_character.facing
		if self._current_weapon is None:
			self._current_weapon = my_character.weapon.name

		if self._current_weapon != my_character.weapon.name and self._last_position is not None:
			# the bot's weapon got changed due to unplanned passing of a tile with one
			# update arena weight in that tile
			self._arena[self._last_position.y, self._last_position.x] = utils.W_PASSAGE
			self._current_weapon = my_character.weapon.name
		self._last_position = my_position
		scanned_tiles = utils.scan_terrain(knowledge.visible_tiles, my_character.facing, self._arena, my_position)
		self._update_arena(scanned_tiles)
		self.weapons_to_take = self._get_weapons_to_take(scanned_tiles[utils.WEAPON], my_position)
		return my_position, my_character, action, current_facing, scanned_tiles

	def _update_arena(self, scanned_tiles):
		if scanned_tiles[utils.MENHIR]:
			self._menhir_coords = scanned_tiles[utils.MENHIR][0]
			self._arena[self._menhir_coords[1], self._menhir_coords[0]] = utils.W_PASSAGE

		for coords in scanned_tiles[utils.PASSAGE]:
			self._arena[coords[1], coords[0]] = utils.W_PASSAGE

		for unpassable in scanned_tiles[utils.SEA] + scanned_tiles[utils.WALL]:
			self._arena[unpassable[1], unpassable[0]] = utils.W_BLOCKERS

		for coords, weapon in scanned_tiles[utils.WEAPON]:
			if utils.WEAPONS_ORDER[weapon] < utils.WEAPONS_ORDER[self._current_weapon]:
				self._arena[coords[1], coords[0]] = utils.W_TAKEN_WEAPON
			else:
				self._arena[coords[1], coords[0]] = utils.W_PASSAGE

		for mist in scanned_tiles[utils.MIST]:
			self._arena[mist[1], mist[0]] = utils.W_MIST

	def _get_weapons_to_take(self, weapons, my_position):
		result = []
		for coords, weapon in weapons:
			if utils.WEAPONS_ORDER[weapon] > utils.WEAPONS_ORDER[self._current_weapon]:
				result.append(coords)
		return sorted(result, key=lambda x: utils.get_distance(x, my_position))

	def standGroundPolicy(self, knowledge: characters.ChampionKnowledge):
		my_position, my_character, action, current_facing, scanned_tiles = self._init_round(knowledge)
		if self._current_state in (utils.GOING_TO_TURN, utils.GOING_TO_MENHIR, utils.GOING_FOR_WEAPON) and action == characters.Action.DO_NOTHING:
			target_position = self._current_path[-1]
			if target_position[0] == my_position.x and target_position[1] == my_position.y:
				if self._current_state != utils.GOING_TO_MENHIR:
					self._current_state = utils.TURN_AROUND
				else:
					self._current_state = utils.CAMPING
				action = characters.Action.TURN_LEFT
				self._turnaround_turns = 0
				return action
			else:
				self._i = self._current_path.index(my_position)
				self._next_move = self._current_path[self._i + 1]
				next_facing = self._get_next_facing(my_position, self._next_move)
				if next_facing is None:
					action = characters.Action.TURN_LEFT
				else:
					action = self._get_action_for_facing(current_facing, next_facing)
				return action

		elif self._current_state == utils.CAMPING and action == characters.Action.DO_NOTHING:
			action = characters.Action.TURN_LEFT
			return action

		return random.choice(POSSIBLE_ACTIONS)


	def armYourselfOrAttackfPolicy(self, knowledge: characters.ChampionKnowledge):
		my_position, my_character, action, current_facing, scanned_tiles = self._init_round(knowledge)
		if utils.able_to_attack(scanned_tiles[utils.ENEMY], knowledge.visible_tiles, my_position,
		                        current_facing, my_character.weapon):
			action = characters.Action.ATTACK
			return action

		if self.weapons_to_take and action == characters.Action.DO_NOTHING:
			weapon_path = None
			i = 0
			while weapon_path is None and i < len(self.weapons_to_take):
				target_coords = Coords(x=self.weapons_to_take[i][0], y=self.weapons_to_take[i][1])
				weapon_path = utils.find_path_to_target(self._arena, my_position, target_coords) or None
				i += 1
			if weapon_path:
				self._i = 1
				self._current_path = weapon_path
				self._next_move = weapon_path[self._i]
				self._current_state = utils.GOING_FOR_WEAPON
				next_facing = self._get_next_facing(my_position, self._next_move)
				if next_facing is None:
					action = characters.Action.TURN_LEFT
				else:
					action = self._get_action_for_facing(current_facing, next_facing)
				self._turnaround_turns = 0
			return action

		return random.choice(POSSIBLE_ACTIONS)

	def wanderPolicy(self, knowledge: characters.ChampionKnowledge):
		my_position, my_character, action, current_facing, scanned_tiles = self._init_round(knowledge)
		if self._menhir_coords is not None and action == characters.Action.DO_NOTHING:
			menhir_coords = Coords(x=self._menhir_coords[0], y=self._menhir_coords[1])
			menhir_path = utils.find_path_to_target(self._arena, my_position, menhir_coords)
			if menhir_path:
				self._i = 1
				self._current_path = menhir_path
				self._next_move = menhir_path[self._i]
				self._current_state = utils.GOING_TO_MENHIR
				next_facing = self._get_next_facing(my_position, self._next_move)
				if next_facing is None:
					action = characters.Action.TURN_LEFT
				else:
					action = self._get_action_for_facing(current_facing, next_facing)
				self._turnaround_turns = 0

		if self._turnaround_turns < ReinforcedMarwin.TURNAROUND_LIMIT and action == characters.Action.DO_NOTHING:
			self._i = 0
			self._found_turns.update(scanned_tiles[utils.TURN])
			if action != characters.Action.ATTACK:
				action = characters.Action.TURN_LEFT
				self._turnaround_turns += 1
			return action
		elif self._turnaround_turns >= ReinforcedMarwin.TURNAROUND_LIMIT and action == characters.Action.DO_NOTHING:
			final_turns = set.union(self._found_turns, scanned_tiles[utils.TURN])
			if len(final_turns.difference(self._previously_found_turns)):
				self._dead_ends.add(my_position)
			self._previously_found_turns.update(self._found_turns)

			self._previously_found_turns.difference_update(self._dead_ends)

			calculated_path = None
			while calculated_path is None:
				turn_index = np.random.choice(len(self._previously_found_turns))
				new_turn_to_go = list(self._previously_found_turns)[turn_index]
				target_coords = Coords(x=new_turn_to_go[0], y=new_turn_to_go[1])
				calculated_path = utils.find_path_to_target(self._arena, my_position, target_coords) or None

			self._i = 1
			self._current_path = calculated_path
			self._next_move = calculated_path[self._i]
			self._current_state = utils.GOING_TO_TURN
			next_facing = self._get_next_facing(my_position, self._next_move)
			if next_facing is None and action != characters.Action.ATTACK:
				action = characters.Action.TURN_LEFT
			elif next_facing is not None and action != characters.Action.ATTACK:
				action = self._get_action_for_facing(current_facing, next_facing)
			self._found_turns.clear()
			self._turnaround_turns = 0
			return action

		return random.choice(POSSIBLE_ACTIONS)

	def ExecuteOrder66Policy(self, knowledge: characters.ChampionKnowledge):  ## will be done for the next round
		pass

	@staticmethod
	def _is_position_occupied(position, tiles):
		return tiles[position].character is not None

	@staticmethod
	def _get_next_facing(current_position, next_position):
		facings = [characters.Facing.LEFT, characters.Facing.RIGHT, characters.Facing.UP, characters.Facing.DOWN]
		for facing in facings:
			if (current_position + facing.value) == next_position:
				return facing
		return None

	@staticmethod
	def _get_action_for_facing(current_facing, next_facing):
		if current_facing == next_facing:
			return characters.Action.STEP_FORWARD
		elif current_facing.turn_right() == next_facing:
			return characters.Action.TURN_RIGHT
		return characters.Action.TURN_LEFT

POTENTIAL_CONTROLLERS = [
	ReinforcedMarwin("Marwin")
]
