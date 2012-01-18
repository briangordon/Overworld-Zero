tiles_world_x = 100
tiles_world_y = 100

tiles_visible_x = 13
tiles_visible_y = 21

tiles_size = 32

chapels_world = 3
castles_world = 16 # must be a multiple of 8
road_length = 25 # plus or minus 5

camps_world = 10
camps_pop = 3 # Number of monsters each camp can support
camps_countdown = 6 # Period between monster spawns at camps

monster_friskiness = 0.2 # probability that the monster will move
monster_radius = 3 # distance away from the target at which monsters will start to chase
monster_giveup = 5 # distance away from the target at which monsters will decide it's uncatchable
monster_tired = 15 # distance away from the home camp at which monsters get tired and leave you alone

inn_cost = 20
inns_world = 6

def exp_req(level):
	if(level is 0):
		return 0
	else:
		return exp_req(level-1) + int(5 * (1.3 ** level))