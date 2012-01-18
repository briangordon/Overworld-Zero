# Copyright (c) 2011 Brian Gordon
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.


# http://sourceforge.net/projects/numpy/files/NumPy/1.6.0/numpy-1.6.0-win32-superpack-python2.6.exe/download


# TO DO:
# Are there circular references foiling the GC?
# Last monster out of a lair should guard it

import os, sys, pygame, config
import random
import noiselib
from noiselib import fBm, simplex_noise2
from noiselib.modules.main import BlendNoise, NoiseArray, RescaleNoise, ScaleBiasNoise, ClampNoise, InvertNoise, MultNoise
from pygame.locals import *
from collections import defaultdict

game = None

#Maps keyboard constants to movement vectors
moves = {K_UP : (0, -1), K_DOWN : (0, 1), K_LEFT : (-1, 0) , K_RIGHT : (1, 0), K_SPACE : (0,0)}

def new_graphic(path):
    graphic = pygame.image.load(path)
    graphic.set_alpha(None)
    graphic.set_colorkey(Color("0xFF0080"))

    return graphic

# namedtuple() is clunky.
#                   Gold, HP, attack power, graphic. 
kinds = {"player" : (0, 10, 1, new_graphic("player.PNG")),
         "swine" : (3, 3, 2, new_graphic("pig.png")),
         "orc" : (5, 4, 2, new_graphic("orc.png"))}

graphics = {"ground" : new_graphic("ground.PNG"), 
            "mountains" : new_graphic("mountains.PNG"),
            "road" : new_graphic("road.PNG"),
            "water" : new_graphic("water.PNG"),
            "castle" : new_graphic("castle.PNG"),
            "chapel" : new_graphic("monastery.PNG"),
            "inn" : new_graphic("inn.PNG"),
            "camp" : new_graphic("camp-1.PNG"),
            "camp_destroyed" : new_graphic("camp-destroyed.PNG"),
            "player_bloody" : new_graphic("player-bloody.PNG"),
            "gold" : new_graphic("gold.PNG"),
            "forest" : new_graphic("forest.PNG")}

def wrap(x,y):
    return (x % config.tiles_world_x, y % config.tiles_world_y)

def distance(start, finish, modulo):
    return min(abs((start - finish)%modulo), abs((finish-start)%modulo))

def distance_pair(start, finish):
    # Return the minimum distance between two points in the modular taxicab geometry

    x1, y1 = start
    x2, y2 = finish

    #System.Math.Min(Mod(a - b, m), Mod(b - a, m));
    return distance(x1, x2, config.tiles_world_x) # x distance
    + distance(y1, y2, config.tiles_world_y) # y distance

def eqmod(start, finish, modulo):
    # Return True if start is congruent to finish
    return (start-finish)%modulo is 0

def gtmod(start, finish, modulo):
    # Return True if on the shortest path between start and finish, start > finish
    d = distance(start, finish, modulo)
    if((start + d)%modulo is finish):
        return False
    if(d is 0):
        return False
    return True

def ltmod(start, finish, modulo):
    # Return True if on the shortest path between start and finish, start < finish
    return (not eqmod(start,finish,modulo)) and (not gtmod(start,finish,modulo))

def export_world(w,capture_run):
    surf = pygame.Surface((config.tiles_world_x * config.tiles_size, config.tiles_world_y * config.tiles_size))

    for x in range(0, config.tiles_world_x):
        for y in range(0, config.tiles_world_y):
            surf.blit(w[x,y].graphic, (x * config.tiles_size, y * config.tiles_size))
            if(w[x,y].occupied_by):
                surf.blit(w[x,y].occupied_by.graphic, (x * config.tiles_size, y * config.tiles_size))

    pygame.image.save(surf, "cap/" + "map" + str(capture_run).zfill(2) + ".PNG")

def generate_camp(world, camps):
    while True:
        x,y = random.randrange(0, config.tiles_world_x), random.randrange(0, config.tiles_world_y)
        if(world[x,y].occupied_by or world[x,y].camp):
            continue
        failed = False
        for i in range(-1,2):
            for j in range(-1,2):
                if(world[wrap(x+i,y+j)].name is not "forest"):
                    failed = True
        if not failed:
            break
    # Pick any kind except the player.
    c = Camp(wrap(x,y), random.choice(kinds.keys()[1:]))
    world[x,y] = Tile(name = "camp", camp = c)
    camps.append(c)

class Tile:
    def __init__ (self, gold = 0, name = "ground", camp = None):
        self.gold = gold
        self.graphic = graphics[name]
        self.occupied_by = None
        self.name = name
        #This is set to a Camp object when self becomes a camp, and is cleared when the camp is disbanded
        #We need to be able to immediately get our hands on the camp object given a tile that a monster just moved into, 
        #to check if it should be disbanded.
        self.camp = camp
        if name in ["mountains", "water"]:
            self.passable = False
        else:
            self.passable = True

    def pass_forai(self):
        return self.passable and (self.occupied_by is None)

class Monster:
    def __init__ (self, pos, kind, camp):
        self.x, self.y = pos
        self.kind = kind
        if(kind is not "dummy"):
            self.gold, self.hp, self.atk, self.graphic = kinds[kind]
            self.totalhp = self.hp
        self.camp = camp
        self.exp = 0
        self.level = 1

        self.following = None

    def ai_move(self, world):
        for d in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            t = world[wrap(self.x+d[0],self.y+d[1])].occupied_by
            if(t):
                if(t.kind is not self.kind):
                    return d

        if self.following and (self.following.kind is not "dummy") and distance_pair((self.x,self.y),(self.following.x,self.following.y)) > config.monster_giveup:
            self.following = None

        if not self.following:
            for x in range(-1 * config.monster_radius, config.monster_radius+1):
                for y in range(-1 * config.monster_radius, config.monster_radius+1):
                    t = world[wrap(self.x+x,self.y+y)].occupied_by
                    if(t and t.kind is not self.kind):
                        self.following = t

        if distance_pair((self.x,self.y),(self.camp.x,self.camp.y)) > config.monster_tired:
            # Create a dummy target monster not in monsters[] or occupying a tile. Self will return to its camp where the
            # dummy target will be removed.
            self.following = Monster((self.camp.x, self.camp.y), "dummy", None)

        if self.following:
            # Determine whether the target is above the follower, to the right, to the left, and/or below.

            xdiff = 0
            if gtmod(self.following.x, self.x, config.tiles_world_x):
                xdiff = 1
            elif ltmod(self.following.x, self.x, config.tiles_world_x):
                xdiff = -1

            ydiff = 0
            if gtmod(self.following.y, self.y, config.tiles_world_y):
                ydiff = 1
            elif ltmod(self.following.y, self.y, config.tiles_world_y):
                ydiff = -1

            # Produce a movement vector based on the orientation of the target. 
            # There's a lot of branch logic here to handle random variables correctly so that rules like 
            # "when chasing you North, a monster running into an obstacle will always go left if it's passable" 
            # don't become exploitable.

            if(xdiff is 0 and ydiff is 0):
                #We've reached our target?! This means that the monster has returned back to a dummy target on its 
                #camp when it loses interest.
                self.following = None

            elif (xdiff is 0):
                if world[wrap(self.x, self.y+ydiff)].pass_forai():
                    return (0, ydiff)
                else: 
                    #We can't move in X so try to dodge the obstacle in Y. Pick a random direction to try first.
                    if random.random() > 0.5:
                        if world[wrap(self.x-1, self.y)].pass_forai():
                            return (-1, 0)
                        else:
                            return (1, 0)
                    else:
                        if world[wrap(self.x+1, self.y)].pass_forai():
                            return (1, 0)
                        else:
                            return (-1, 0)

            elif (ydiff is 0):
                if world[wrap(self.x+xdiff, self.y)].pass_forai():
                    return (xdiff, 0) 
                else:
                    #We can't move in Y so try to dodge the obstacle in X. Pick a random direction to try first.
                    if random.random() > 0.5:
                        if world[wrap(self.x, self.y-1)].pass_forai():
                            return (0, -1)
                        else:
                            return (0, 1)
                    else:
                        if world[wrap(self.x, self.y+1)].pass_forai():
                            return (0, 1)
                        else:
                            return (0, 1)

            else:
                #We can make progress in either dimension. Pick a random direction to try first.
                if random.random() > 0.5:
                    if world[wrap(self.x, self.y+ydiff)].pass_forai():
                        return (0, ydiff)
                    elif world[wrap(self.x+xdiff, self.y)].pass_forai():
                        return (xdiff, 0)
                else:
                    if world[wrap(self.x+xdiff, self.y)].pass_forai():
                        return (xdiff, 0)
                    elif world[wrap(self.x, self.y+ydiff)].pass_forai():
                        return (0, ydiff)


        # If no enemies are around, move randomly half the time.
        if(random.random() < config.monster_friskiness):
            return random.choice([(-1, 0), (1, 0), (0, -1), (0, 1)])

        return (0,0)

    # The return value is True when a monster is killed and it comes before the killer in the monsters list.
    # This is because of the weirdness involved in removing elements from monsters as we iterate over it.
    def move(self, direction, world, camps, monsters):
        newx, newy = wrap(self.x + direction[0], self.y + direction[1])
        t = world[newx, newy]
        messages = []

        #Return a killed monster/player, or None if nothing is killed
        killed = None
        if t.passable:
            if(t.occupied_by is None):
                world[self.x, self.y].occupied_by = None
                t.occupied_by = self
                self.x = newx
                self.y = newy

                if(self.kind is "player" and t.gold > 0):
                    messages.append("You picked up " + str(t.gold) + " GP.")

                self.gold += t.gold
                t.gold = 0

                # Disband any camp here
                if t.camp and (t.camp.kind is not self.kind):
                    if(self.kind is "player"):
                        messages.append(t.camp.kind + " camp disbanded.")
                    camps.remove(t.camp)
                    self.gold += (kinds[t.camp.kind][0] * 5) #Gold bonus for disbanding the camp
                    t.camp = None
                    t.name = "camp_destroyed"
                    t.graphic = graphics["camp_destroyed"]
                    generate_camp(world, camps)

                if(self.kind is "player" and t.name is "inn" and self.hp < self.totalhp):
                    if(self.gold >= config.inn_cost):
                        messages.append("You heal at the inn.")
                        self.gold = self.gold - config.inn_cost
                        self.hp = self.totalhp
                    else:
                        messages.append("Come back when you have " + str(config.inn_cost) + " gold.")

            elif(t.occupied_by.kind is not self.kind):
                if(random.random() < 0.4):
                    if(self.kind is "player"):
                        messages.append("You hit the " + t.occupied_by.kind + " for " + str(self.atk + self.level) + " HP")
                    if(t.occupied_by.kind is "player"):
                        messages.append("The " + self.kind + " hit you for " + str(self.atk + self.level) + " HP")
                    t.occupied_by.hp = t.occupied_by.hp - (self.atk + self.level) #level damage bonus
                    if(t.occupied_by.hp <= 0):
                        killed = t.occupied_by
                        if(self.kind is "player"):
                            messages.append("You killed the " + killed.kind + ", gaining " + str(killed.level) + " XP")
                        if(killed.kind is "player"):
                            messages.append("You have been killed by the " + self.kind)

                        self.exp += killed.level
                        if(self.exp >= config.exp_req(self.level)):
                            self.level += 1 #Level up
                            self.totalhp += 2
                            self.hp += 2
                            if(self.kind is "player"):
                                messages.append("You have leveled up.")

                        if(killed.kind is not "player"): #Leave the player's corpse visible
                            t.occupied_by = None
                        t.gold = killed.gold
                        if(killed.camp):
                            killed.camp.population -= 1
                        oldmonsters = monsters[:]
                        if killed.kind is not "player":
                            monsters.remove(killed)
                            if (self.kind is not "player" and oldmonsters.index(killed) <= oldmonsters.index(self)):
                                return messages, True

                else:
                    if(self.kind is "player"):
                        messages.append("You missed the " + t.occupied_by.kind)
                    if(t.occupied_by.kind is "player"):
                        messages.append("The " + self.kind + " missed you")


        return messages, False



class Camp:
    def __init__ (self, pos, kind):
        self.x, self.y = pos
        self.kind = kind
        self.population = 0
        self.countdown = config.camps_countdown

    def spawn(self, world, monsters):
        t = world[self.x, self.y]
        if(t.occupied_by is None):
            m = Monster((self.x, self.y), self.kind)
            world[self.x, self.y].occupied_by = m
            monsters.append(m)

class Game:
    def hudprint(self,text,xx,yy):
        font = pygame.font.SysFont("freesansbold.ttf",18)
        ren = font.render(text,0,Color("0x0000FF"),Color("0x000000"))
        self.screen.blit(ren, (xx,yy))

    def messprint(self,messages):
        xx, yy = 1, 30
        for m in messages:
            font = pygame.font.SysFont(None,30)
            ren = font.render(m,0,Color("0x00FF00"))
            self.screen.blit(ren, (xx,yy))
            yy += 30

    def main(self):          
        pygame.mixer.init(frequency=44100, size=8, channels=1, buffer=4096)
        os.environ["SDL_VIDEO_CENTERED"] = "1"
        pygame.init()

        #pygame.mixer.music.load("music.wav")
        #pygame.mixer.music.play(-1)


        icon = pygame.image.load("player.PNG")
        icon.set_alpha(None)
        icon.set_colorkey(Color("0xFF0080"))
        pygame.display.set_icon(icon)

        self.screen = pygame.display.set_mode((config.tiles_visible_x * config.tiles_size, config.tiles_visible_y * config.tiles_size))
        pygame.display.set_caption("Overworld Zero Point Zero One")

        # Generate world

        noiselib.init(256)
        world = defaultdict(Tile)

        # Add forests

        source = fBm(5, 0.6, simplex_noise2)
        source = ScaleBiasNoise(1, 1, source)
        source = RescaleNoise((-1, 1), (0, 1), source)

        for y in range(0, config.tiles_world_y):
            for x in range(0, config.tiles_world_x):
                if(source((x,y)) < 1.0):
                    world[x,y] = Tile(name = "forest")

        #source = fBm(4, 0.4, simplex_noise2)
        #source = ScaleBiasNoise(1, 1, source)
        #source = RescaleNoise((-1, 1), (0, 1), source)

        #for y in range(0, config.tiles_world_y):
        #    for x in range(0, config.tiles_world_x):
        #        if(source((x,y)) < 0.9):
        #            world[x,y] = Tile(name = "forest")

        # Add mountain ranges

        source = fBm(6, 0.2, simplex_noise2, "ridged")
        source = ScaleBiasNoise(1, -0.6, source)
        source = ClampNoise(0,10,source)

        source_2 = fBm(7, 0, simplex_noise2, "billow")
        source_2 = ScaleBiasNoise(1, 0.2, source_2)
        source_2 = InvertNoise(source_2)
        source_2 = ClampNoise(0,10,source_2)
        source = MultNoise(source, source_2)

        for y in range(0, config.tiles_world_y):
            for x in range(0, config.tiles_world_x):
                if(source((x,y)) > 0):
                    world[x,y] = Tile(name = "mountains")

        # Add lakes

        source = fBm(6, 0.05, simplex_noise2, f = 'billowed')
        source = ScaleBiasNoise(1, 1.4, source)
        source = RescaleNoise((-1, 1), (0, 1), source)

        for y in range(0, config.tiles_world_y):
            for x in range(0, config.tiles_world_x):
                if(source((x,y)) < 1.0):
                    world[x,y] = Tile(name = "water")


        # Add roads with a castle at each end

        yoffset = 0
        xoffset = 0

        for i in range(0, config.castles_world):
            intersect = False #If we run into another road, create an intersection
            distance = random.randrange(config.road_length-5, config.road_length+6)

            # Put an equal number of castles in each eighth of the map to even out the distribution
            y = yoffset + random.randrange(0, config.tiles_world_y / 2 + 1)
            x = xoffset + random.randrange(0, config.tiles_world_x / 4 + 1)
            x, y = wrap(x, y)

            xoffset, yoffset = wrap(xoffset + (config.tiles_world_x / 4), yoffset + (config.tiles_world_y / 2))
            horiz = random.random() < 0.5

            world[x,y] = Tile(name = "castle")
            while(distance > 0):
                if(random.random() > 0.15):
                    if horiz:
                        x+=1
                    else:
                        y+=1
                else:
                    if horiz:
                        y+=1
                    else:
                        x+=1
                distance -= 1
                x,y = wrap(x,y)

                if(world[x,y].name is "road"):
                    intersect = True
                    break

                world[x,y] = Tile(name = "road")
            
            #Create the castle at the other endpoint
            if not intersect:
                world[x,y] = Tile(name = "castle")

        # Add chapels

        for i in range(0, config.chapels_world):
            while True:
                x,y = random.randrange(0, config.tiles_world_x), random.randrange(0, config.tiles_world_y)
                if(world[x,y].name is "ground"):
                    break
            world[x,y] = Tile(name = "chapel")

        # Add inns

        for i in range(0, config.inns_world):
            while True:
                x,y = random.randrange(0, config.tiles_world_x), random.randrange(0, config.tiles_world_y)
                if(world[x,y].name is "ground"):
                    break
            world[x,y] = Tile(name = "inn")
        
        # Place the player
        
        while True:
            px, py = random.randrange(0, config.tiles_world_x), random.randrange(0, config.tiles_world_y)
            if(world[px,py].passable):
                break
        
        player = Monster(pos = (px, py), kind="player", camp=None)
        world[px,py].occupied_by = player

        # Populate with monsters

        monsters = []
        camps = []

        for i in range(0, config.camps_world):
            generate_camp(world, camps)
        
        #Are we currently recording?
        recording = False 
        frame = 0
        capture_run = 0
        
        #Is this the first draw where monsters shouldnt move?
        initialize = True

        #Is the game over?
        dead = False

        #Main game loop
        while 1:
            if not initialize:
                event = pygame.event.wait()

                if event.type == QUIT:
                    return
                if event.type == KEYDOWN:
                    if event.key is K_q:
                        return
                    elif event.key is K_r:
                        if not recording:
                            capture_run += 1
                            export_world(world, capture_run)
                        recording = not recording
                        initialize = True
                    elif event.key in moves.keys():
                        moving = moves[event.key]
                    else:
                        continue
                else:
                    continue

            if(dead):
                return

            self.screen.fill(Color(0,0,0))

            mess = []

            #Make the player's move first, and move each monster in monsters

            if not initialize:
                if moving != (0,0):
                    mess, dummy = player.move(moving, world, camps, monsters)

                # Be careful here; modifying a list mid-iteration is tricky
                i = 0
                while i < len(monsters):
                    m = monsters[i]
                    # No need to increment i if a monster has been removed earlier in the list
                    messages, result = m.move(m.ai_move(world), world, camps, monsters)
                    mess.extend(messages)
                    if not result:
                        i += 1
            
            # Spawn at camps

            for c in camps:
                if(c.population < config.camps_pop):
                    c.countdown -= 1
                if(c.countdown <= 0):
                    t = world[c.x,c.y]
                    if t.occupied_by is None:
                        c.countdown = config.camps_countdown
                        c.population += 1
                        m = Monster((c.x,c.y), c.kind, c)
                        monsters.append(m)
                        t.occupied_by = m

            if(player.exp > 0):
                player.graphic = graphics["player_bloody"]

            #Detect if the player has died.
            if(player.hp <= 0):
                player.graphic = new_graphic("player-dead.PNG")
                dead = True
            
            initialize = False

            for x in range(0, config.tiles_visible_x):
                for y in range(0, config.tiles_visible_y):
                    t_coord = wrap(player.x - (config.tiles_visible_x / 2) + x, player.y - (config.tiles_visible_y / 2) + y)
                    t = world[t_coord]

                    self.screen.blit(t.graphic, (x * config.tiles_size, y * config.tiles_size))
                    if(t.occupied_by):
                        self.screen.blit(t.occupied_by.graphic, (x * config.tiles_size, y * config.tiles_size))
                    if(t.gold > 0):
                        self.screen.blit(graphics["gold"], (x * config.tiles_size, y * config.tiles_size))

            self.hudprint("X: " + str(player.x) + " Y: " + str(player.y), 0, 0)
            self.messprint(mess)

            self.hudprint("LV: " + str(player.level), 0, self.screen.get_height()-18)
            self.hudprint("HP: " + str(player.hp) + "/" + str(player.totalhp), 50, self.screen.get_height()-18)
            self.hudprint("GP: " + str(player.gold), 150, self.screen.get_height()-18)
            self.hudprint("XP: " + str(player.exp) + "/" + str(config.exp_req(player.level)), 250, self.screen.get_height()-18)

            #Swap display buffers
            pygame.display.update()

            if(recording):
                #Export the screen surface to a PNG file for making videos. This can use a lot of disk space if you record for more 
                #than a few seconds. PNG compression kills the frame rate, but the file sizes are much more manageable. 
                pygame.image.save(self.screen, "cap/" + "run" + str(capture_run).zfill(2) + "_f" + str(frame).zfill(5) + ".PNG")
                frame += 1

def run():
    global game
    game = Game()
    game.main()