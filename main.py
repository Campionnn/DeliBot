import asyncio
import atexit
import io
import os
import sys
import threading
import time
from difflib import get_close_matches

import cv2
import discord
import keyboard
import pyautogui
import numpy as np
import pytesseract
import requests
import win32gui
import autoit
from PIL import ImageGrab, Image
from discord import app_commands

# scuffed exec if running as exe
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    try:
        exec(open("config.py").read())
        exec(open("screen.py").read())
    except FileNotFoundError:
        pass
else:
    try:
        from config import *
        from screen import *
    except ModuleNotFoundError:
        pass

pytesseract.pytesseract.tesseract_cmd = None
roblox = None
ownerID = 0
slotsCord = []
inventory = ["" for _ in range(20)]
inventoryStack = [1 for _ in range(20)]
goodSlots = []
inventoryBBox = [[0, 0], [0, 0]]
inventorySShot: Image = None
paused = False
logFile = ""
logText = []
waitTimes = []


template_screen = r"""slotsCordRef = {
    "upperLeft": upperLeftPos,  # coordinates of upper-left inventory slot (x, y)
    "difference": differencePos  # difference in pixels between each inventory slot (x, y)
}

nameCord = [  # coordinates upper-left and lower-right bounding box of item name in inventory (x, y)
    nameCord1Pos,
    nameCord2Pos
]

inventoryCord = invPos  # coordinate of purple background behind "Vanity"
inventoryColor = invC   # corresponding color

ringText = ringPos  # coordinates of any white part in "Ring Bell"
ringColor = ringgC  # corresponding color should be (255, 255, 255)

shortCord = shortPos  # coordinates of the short and long wait option
longCord = longPos

dialogueCord = dialPos  # coordinates of any green part of dialogue near the bottom right
dialogueColor = dialC  # corresponding color
"""

template_config = r"""tesseractLocation = r"C:\Program Files\Tesseract-OCR\tesseract.exe"  # location of tesseract
botToken = ""  # discord bot token
serverID = 0  # discord server id

deliType = "long"  # "short" or "long"
deliMaxWait = 3600  # maximum time to wait for deli before failsafe

dialogueWaitMultiplier = 1.0  # Multiply dialogue wait times by this number for slower PCs

itemNotifValue = 900000  # value of received item to be notified in discord
forceStart = True  # True or False to skip the prompt to click start

keepItem = {  # prices of items you can receive from deli
    "Green Bean": 95000,
    "Blue Bean": 150000,
    "Red Bean": 400000,
    "Kitchen Cube": 100000,
    "Clever Cube": 250000,
    "Century Cube": 1500000,
    "Gift Fruit": 700000,
    "Lesser Dungeon Candy": 4000,
    "Greater Dungeon Candy": 10000,
    "Minion": 1777777,
    "Noble Blue Seed": 88000,
    "White Salamander Egg": 200000,
    "Tall Anthony": 5000000,
    "The Crown": 1000000,
    "Court Jester Shirt": 900000,
    "Court Jester Pants": 900000,
    "Pantry Leech Head": 1000000,
    "Pantry Leech Torso": 1000000,
    "Pantry Leech Platelegs": 1000000,
    "The Drake's Torso": 900000,
    "The Drake's Legs": 900000,
    "Buttered Greens with Extra Butter": 25000,
    "Red Yesterday Hat": 25000,
    "Big Chicken": 9000,
    "Candy Crumbs": 15,
    "Gnome Rocket": 100,
    "Bullet": 100
}

itemStack = [  # kept items that can be stacked
    "Lesser Dungeon Candy",
    "Greater Dungeon Candy",
    "Big Chicken",
    "Candy Crumbs",
    "Gnome Rocket",
    "Bullet"
]"""


def kill():
    keyboard.wait('del')
    print("Del key detected. Quitting")
    exit_handler()
    os._exit(0)


async def log_item(text):
    global logText, GUI_view, GUI_embed, GUI_log_text
    print(text)
    logText.append(f"{time.strftime('%H:%M:%S')} {text}")
    with open(logFile, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {text}\n")

    send_text = ""
    actual_count = 0
    log_text_cut = logText[-50:]
    for line in log_text_cut:
        send_text = '\n'.join([send_text, line])
        actual_count += 1

    GUI_log_text = f"```\nLast {actual_count} lines in log:\n{send_text}```"

    if GUI_menu == "log":
        GUI_log()

        await update_GUI()


async def update_wait():
    global GUI_wait_text
    wait_text = ""
    actual_count = 0
    wait_times = waitTimes[-100:]
    for wait in wait_times:
        wait_text = '\n'.join([wait_text, f"{wait:.2f}"])
        actual_count += 1

    GUI_wait_text = f"Average wait time for {deliType} wait: {sum(waitTimes) / len(waitTimes):.2f}\nMin wait: {min(waitTimes):.2f}\nMax wait: {max(waitTimes):.2f}\nTotal orders completed: {len(waitTimes)}\n```\nLast {actual_count} wait times:\n{wait_text}```"

    if GUI_menu == "wait":
        GUI_wait()

        await update_GUI()


async def notif_item(name):
    await GUI_message.channel.send(f"<@{ownerID}> Received {name} worth {keepItem[name]} gold")


def inventory_value():  # get value of inventory
    value = 0
    for item in list(filter(lambda x: x != "", inventory)):
        if item in keepItem:
            value += keepItem[item] * inventoryStack[inventory.index(item)]
    return value


async def open_inventory():
    win32gui.SetForegroundWindow(roblox)
    win32gui.ShowWindow(roblox, 3)
    if not await wait_pixel(inventoryCord[0], inventoryCord[1], inventoryColor, interval=0.5, timeout=5, keypress='q'):
        print("Failed to open inventory. Attempting failsafe")
        win32gui.SetForegroundWindow(roblox)
        win32gui.ShowWindow(roblox, 3)
        autoit.mouse_click("left", speed=2)
        if not await wait_pixel(inventoryCord[0], inventoryCord[1], inventoryColor, interval=0.5, timeout=5, keypress='q'):
            print("Failed to open inventory. Exiting")
            exit_handler()
            os._exit(0)


async def inventory_screenshot():
    global inventorySShot, GUI_inventory, GUI_inventoryID, GUI_embed
    inventorySShot = ImageGrab.grab(bbox=(inventoryBBox[0][0], inventoryBBox[0][1], inventoryBBox[1][0], inventoryBBox[1][1]))
    with io.BytesIO() as image_binary:
        inventorySShot.save(image_binary, 'PNG')
        image_binary.seek(0)
        image_message = await GUI_data_channel.send(file=discord.File(fp=image_binary, filename="inventory.png"))
    GUI_inventory = image_message.attachments[0].url
    GUI_inventoryID = image_message.id
    if GUI_menu == "main":
        GUI_embed.set_image(url=image_message.attachments[0].url)
        GUI_embed.description = f"Total value of inventory: {inventory_value():,}"

        await update_GUI()


async def inventory_item_count(slot):  # get number of items in a slot
    bgr_value = (43, 124, 54)
    b_tolerance = 1
    g_tolerance = 0.75
    r_tolerance = 0.75
    upper_multiplier = .8
    lower_multiplier = .4
    size_multiplier = 5
    difference = slotsCordRef["difference"]
    item_x1 = round(slotsCord[slot][0] - difference[0] * 0.45)
    item_y1 = round(slotsCord[slot][1] - difference[0] * 0)
    item_x2 = round(slotsCord[slot][0] + difference[0] * 0.45)
    item_y2 = round(slotsCord[slot][1] + difference[1] * 0.4)
    item_image = ImageGrab.grab(bbox=(item_x1, item_y1, item_x2, item_y2))

    # cv2.imshow("test", np.array(item_image))
    # cv2.waitKey(0)

    # convert image to numpy array, change to BGR, and resize
    im_arr = np.array(item_image)
    im_arr = cv2.cvtColor(im_arr, cv2.COLOR_RGB2BGR)
    im_arr = cv2.resize(im_arr, (0, 0), fx=size_multiplier, fy=size_multiplier, interpolation=cv2.INTER_CUBIC)

    # mask image within tolerance of bgr_value
    lower = np.array(
        [bgr_value[0] * (1 - b_tolerance * lower_multiplier),
         bgr_value[1] * (1 - g_tolerance * lower_multiplier),
         bgr_value[2] * (1 - r_tolerance * lower_multiplier)])
    upper = np.array(
        [bgr_value[0] * (1 + b_tolerance * upper_multiplier),
         bgr_value[1] * (1 + g_tolerance * upper_multiplier),
         bgr_value[2] * (1 + r_tolerance * upper_multiplier)])
    mask = cv2.inRange(im_arr, lower, upper)
    im_arr[mask == 0] = (255, 255, 255)
    im_arr[mask != 0] = (0, 0, 0)

    # convert image to grayscale and apply Otsu's thresholding
    gray = cv2.cvtColor(im_arr, cv2.COLOR_BGR2GRAY)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    # remove noise and  dilate to connect text regions
    open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
    opening = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, open_kernel, iterations=1)
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    dilate = cv2.morphologyEx(opening, cv2.MORPH_DILATE, dilate_kernel, iterations=2)

    # find contours and get rid of small ones
    cnts = cv2.findContours(dilate, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = cnts[0] if len(cnts) == 2 else cnts[1]
    for c in cnts:
        area = cv2.contourArea(c)
        if area < 200:
            cv2.drawContours(dilate, [c], -1, 0, -1)

    # reverse image and apply blur
    result = 255 - dilate
    result = cv2.GaussianBlur(result, (3, 3), 0)

    # dilate text a lot to get contour and bounding box
    text_kerenel = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 20))
    text_dilate = cv2.dilate(dilate, text_kerenel, iterations=1)
    contours, hierarchy = cv2.findContours(text_dilate, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # get the lowest bounding box and use in OCR
    maxcord = 0
    number = None
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        cord = y + h
        if cord > maxcord:
            maxcord = cord
            number = result[y:y + h, x:x + w]

    # OCR final number
    count = pytesseract.image_to_string(number, timeout=5, config='--psm 6 --oem 3 -c tessedit_char_whitelist=0123456789')

    if count == "" or int(count) == 0:
        print(f"Failed to get stack count of {inventory[slot]}")
        print("Saving images for debugging")
        if not os.path.exists("images"):
            os.makedirs("images")
        item_image.save(f"images/item{slot}-orig {time.strftime('%H-%M-%S')}.png")
        cv2.imwrite(f"images/item{slot}-num {time.strftime('%H-%M-%S')}.png", number)
        return 1
    return int(count)


async def inventory_item_name():
    image = ImageGrab.grab(bbox=(nameCord[0][0], nameCord[0][1], nameCord[1][0], nameCord[1][1])).convert('L')
    im_arr = np.array(image)
    mask = np.all(im_arr[..., :3] != (255, 255, 255), axis=-1)
    im_arr[mask, :3] = (0, 0, 0)
    name = pytesseract.image_to_string(im_arr, timeout=5).rstrip()
    return name


async def init_inventory():
    dropped = False
    await open_inventory()
    for slot, (x, y) in enumerate(slotsCord):
        autoit.mouse_click("left", x, y, speed=2)
        name = await inventory_item_name()
        if name == "":
            continue
        match_name = get_close_matches(name, keepItem, n=1, cutoff=.8)
        if match_name:
            name = str(match_name[0])
            inventory[slot] = name
            goodSlots.append(slot)
            if name in itemStack:
                item_count = await inventory_item_count(slot)
                inventoryStack[slot] = item_count
                await log_item(f"Kept {item_count} {name}")
                continue
            else:
                await log_item(f"Kept {name}")
                continue
        else:
            autoit.mouse_click("right", x, y, speed=2)
            autoit.mouse_click("left", x+10, y+5, speed=2)
            dropped = True
            await log_item(f"Dropped {name}")
            continue
    await asyncio.sleep(0.5)
    await inventory_screenshot()
    keyboard.send('q')
    await asyncio.sleep(0.25)
    if dropped:
        keyboard.press('w')
        await asyncio.sleep(0.25)
        keyboard.release('w')
        keyboard.press('a')
        await asyncio.sleep(0.25)
        keyboard.release('a')


async def clean_inventory():
    dropped = False
    await open_inventory()
    try:
        slot = inventory.index("")
    except ValueError:
        raise Exception("inventory full")
    x = slotsCord[slot][0]
    y = slotsCord[slot][1]
    autoit.mouse_click("left", x, y, speed=2)
    name = await inventory_item_name()
    match_name = get_close_matches(name, keepItem, n=1, cutoff=.8)
    if name == "":
        received = False
        for _slot in goodSlots:
            if inventory[_slot] in itemStack:
                count = await inventory_item_count(_slot)
                if count == inventoryStack[_slot]:
                    continue
                elif count > inventoryStack[_slot]:
                    difference = count - inventoryStack[_slot]
                    inventoryStack[_slot] = count
                    if received:
                        print(f"Found another stack increase for {inventory[_slot]}")
                        await log_item(f"Also received {difference} {inventory[_slot]}")
                        continue
                    received = True
                    await log_item(f"Received {difference} {inventory[_slot]}")
                    continue
                elif count < inventoryStack[_slot]:
                    difference = inventoryStack[_slot] - count
                    inventoryStack[_slot] = count
                    print(f"Incorrect stack count for {inventory[_slot]}")
                    print(f"Correcting stack count to {count}")
                    await log_item(f"Corrected {inventory[_slot]} to {count}")
                    await log_item(f"Lost {difference} {inventory[_slot]}")
                    continue
    elif match_name:
        name = str(match_name[0])
        inventory[slot] = name
        goodSlots.append(slot)
        if name in itemStack:
            count = await inventory_item_count(slot)
            inventoryStack[slot] = count
            await log_item(f"Received {count} {name}")
        else:
            await log_item(f"Kept {name}")
            if keepItem[name] >= itemNotifValue:
                await notif_item(name)
    else:
        autoit.mouse_click("right", x, y, speed=2)
        autoit.mouse_click("left", x+10, y+5, speed=2)
        await log_item(f"Dropped {name}")
        dropped = True
    await asyncio.sleep(0.5)
    await inventory_screenshot()
    keyboard.send('q')
    await asyncio.sleep(0.25)
    if dropped or waitTimes[-1] < 90:
        keyboard.press('w')
        await asyncio.sleep(0.25)
        keyboard.release('w')
        keyboard.press('a')
        await asyncio.sleep(0.25)
        keyboard.release('a')


async def wait_pixel(x, y, color="0xFFFFFF", interval=0.1, timeout=1, antiafk=False, keypress=None):  # wait until a pixel matches color
    time_exit = time.time() + timeout
    time_afk = time.time()
    while pyautogui.pixel(x, y) != color:
        if keypress:
            keyboard.send(keypress)
        if antiafk:
            if time.time() - time_afk > 600:
                autoit.mouse_click("left", speed=2)
                time_afk = time.time()
        if time.time() > time_exit:
            return False
        await asyncio.sleep(interval)
    return True


async def start_food():
    if not await wait_pixel(ringText[0], ringText[1], color=ringColor, interval=0.5, timeout=30, keypress='e'):
        print("Failed to enter booth. Attempting fail safe")
        keyboard.press('w')
        await asyncio.sleep(0.25)
        keyboard.release('w')
        keyboard.press('d')
        await asyncio.sleep(0.25)
        keyboard.release('d')
        if not await wait_pixel(ringText[0], ringText[1], color="0xFFFFFF", interval=0.5, timeout=5, keypress='e'):
            print("Completely failed to enter booth. Exiting")
            exit_handler()
            os._exit(0)
    autoit.mouse_click("left", ringText[0], ringText[1], speed=2)
    await asyncio.sleep(3.25 * dialogueWaitMultiplier)
    autoit.mouse_click("left", dialogueCord[0], dialogueCord[1], speed=2)
    await asyncio.sleep(2.25 * dialogueWaitMultiplier)
    autoit.mouse_click("left", dialogueCord[0], dialogueCord[1], speed=2)
    await asyncio.sleep(2.25 * dialogueWaitMultiplier)
    autoit.mouse_click("left", dialogueCord[0], dialogueCord[1], speed=2)
    await asyncio.sleep(0.5 * dialogueWaitMultiplier)
    if deliType == "short":
        autoit.mouse_click("left", shortCord[0], shortCord[1], speed=2)
    else:
        autoit.mouse_click("left", longCord[0], longCord[1], speed=2)
    await asyncio.sleep(1 * dialogueWaitMultiplier)
    autoit.mouse_click("left", dialogueCord[0], dialogueCord[1], speed=2)
    wait_start = time.time()
    if not await wait_pixel(dialogueCord[0], dialogueCord[1], color=dialogueColor, interval=1, antiafk=True, timeout=deliMaxWait):
        print("Stuck in deli booth longer than max wait time. Exiting")
        exit_handler()
        os._exit(0)
    waitTimes.append(time.time() - wait_start)
    await update_wait()
    await asyncio.sleep(1.5 * dialogueWaitMultiplier)
    autoit.mouse_click("left", dialogueCord[0], dialogueCord[1], speed=2)
    await asyncio.sleep(1 * dialogueWaitMultiplier)
    autoit.mouse_click("left", dialogueCord[0], dialogueCord[1], speed=2)


async def main():
    # set roblox to foreground
    global roblox
    roblox = win32gui.FindWindow(None, "Roblox")
    win32gui.SetForegroundWindow(roblox)
    win32gui.ShowWindow(roblox, 3)

    await init_inventory()

    while True:
        await asyncio.sleep(0.25)
        await start_food()
        await asyncio.sleep(0.25)
        await clean_inventory()
        time_afk = time.time()
        while paused:
            if time.time() - time_afk > 600:
                autoit.mouse_click("left", speed=2)
                time_afk = time.time()
            await asyncio.sleep(1)


# ==================================================Discord Bot Stuff==================================================

try:
    MY_GUILD = discord.Object(id=serverID)
except NameError:
    MY_GUILD = 0

GUI_channel: discord.TextChannel = None
GUI_guild: discord.Guild = None
GUI_data_channel: discord.TextChannel = None
GUI_message: discord.Message = None
GUI_embed: discord.Embed = None
GUI_view: discord.ui.View = None
GUI_view_start: discord.ui.View = None
GUI_view_main: discord.ui.View = None
GUI_view_back: discord.ui.View = None
GUI_view_log: discord.ui.View = None
GUI_view_wait: discord.ui.View = None
GUI_view_screen: discord.ui.View = None
GUI_view_quit: discord.ui.View = None
GUI_menu = ""
GUI_inventory = ""
GUI_inventoryID = 0
GUI_log_text = ""
GUI_wait_text = ""


class BotClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)


intents = discord.Intents.default()
client = BotClient(intents=intents)


def GUI_start():
    global GUI_embed, GUI_view, GUI_menu
    GUI_view = GUI_view_start

    GUI_embed = discord.Embed(title="DeliBot",
                              color=0x226919,
                              description="Go to the Deli, stand on the shown booth, and look almost straight down then start the bot\n"
                                          "If you look straight down, movement keys won't work\n"
                                          "Reference image below\n"
                                          "**IMPORTANT**: Press the Del key or use the quit button to stop the script"
                              )
    GUI_embed.set_image(url="https://cdn.discordapp.com/attachments/792495578486669313/1059209748496527380/image.png")

    GUI_menu = "start"


def GUI_mainmenu():
    global GUI_embed, GUI_view, GUI_menu
    GUI_view = GUI_view_main

    GUI_embed = discord.Embed(title="Deli Bot", color=0x226919)

    if GUI_inventory:
        GUI_embed.set_image(url=GUI_inventory)
        GUI_embed.description = f"Total value of inventory: {inventory_value():,}"
    else:
        GUI_embed.description = "Inventory not scanned yet"

    GUI_menu = "main"


def GUI_log():
    global GUI_embed, GUI_view, GUI_menu

    with open(logFile, "r") as f:
        log_text = f.read().splitlines()
    if len(log_text) == 0:
        GUI_embed.set_image(url="")
        GUI_embed.description = "Log is empty"

        GUI_view = GUI_view_back
        return

    GUI_embed.set_image(url="")
    GUI_embed.description = GUI_log_text

    GUI_view = GUI_view_log

    GUI_menu = "log"


def GUI_wait():
    global GUI_wait_text, GUI_embed, GUI_view, GUI_menu
    if len(waitTimes) == 0:
        GUI_embed.set_image(url="")
        GUI_embed.description = "No orders have been completed yet"

        GUI_view = GUI_view_back
        return

    wait_text = ""
    actual_count = 0
    wait_times = waitTimes[-50:]
    for wait in wait_times:
        wait_text = '\n'.join([wait_text, f"{wait:.2f}"])
        actual_count += 1

    GUI_embed.set_image(url="")
    GUI_embed.description = GUI_wait_text

    GUI_view = GUI_view_wait

    GUI_menu = "wait"


def GUI_quit():
    global GUI_embed, GUI_view, GUI_menu

    GUI_embed.set_image(url="")
    GUI_embed.description = "Are you sure you want to quit?"

    GUI_view = GUI_view_quit

    if GUI_menu == "start":
        GUI_menu = "startquit"
    else:
        GUI_menu = "quit"


def exit_handler():
    if GUI_message:
        requests.delete(f"https://discordapp.com/api/channels/{GUI_message.channel.id}/messages/{GUI_message.id}",
                        headers={"Authorization": f"Bot {botToken}"}
                        )


class startButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Start", style=discord.ButtonStyle.green, custom_id="start", row=0, emoji=discord.PartialEmoji(name="▶️"))

    async def callback(self, interaction: discord.Interaction):
        GUI_mainmenu()

        await update_GUI(interaction)
        print("Bot started")
        await main()


class backButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Back", style=discord.ButtonStyle.blurple, custom_id="back", row=0, emoji=discord.PartialEmoji(name="⬅️"))

    async def callback(self, interaction: discord.Interaction):
        GUI_mainmenu()

        await update_GUI(interaction)


class pauseButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Pause", style=discord.ButtonStyle.grey, custom_id="pause", row=0, emoji=discord.PartialEmoji(name="⏸️"))

    async def callback(self, interaction: discord.Interaction):
        global paused
        if paused is False:
            paused = True
            GUI_view.children[0].label = "Resume"
            GUI_view.children[0].style = discord.ButtonStyle.green
            GUI_view.children[0].emoji = discord.PartialEmoji(name="▶️")
            print("Paused bot")
        else:
            paused = False
            GUI_view.children[0].label = "Pause"
            GUI_view.children[0].style = discord.ButtonStyle.grey
            GUI_view.children[0].emoji = discord.PartialEmoji(name="⏸️")
            print("Resumed bot")

        await update_GUI(interaction)


# class inventoryButton(discord.ui.Button):
#     def __init__(self):
#         super().__init__(label="Inventory", style=discord.ButtonStyle.blurple, custom_id="inventory", row=0, emoji=discord.PartialEmoji(name="📦"))
#
#     async def callback(self, interaction: discord.Interaction):
#         global GUI_inventory, GUI_inventoryID
#         GUI_inventory = inventory_image()
#         GUI_inventoryID = 0
#
#         GUI_mainmenu()
#
#         await update_GUI(interaction)
#         print("Viewed inventory")
#
#         inv_text = ""
#         for i, item in enumerate(inventory):
#             inv_text += f"{i + 1}: {item} "
#             if inventoryStack[i] > 1:
#                 inv_text += f"x {inventoryStack[i]}"
#             inv_text += "\n"


class logButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Logs", style=discord.ButtonStyle.blurple, custom_id="logs", row=1, emoji=discord.PartialEmoji(name="📝"))

    async def callback(self, interaction: discord.Interaction):
        GUI_log()

        await update_GUI()
        print("Viewed item log")


class logDownloadButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Get Download", style=discord.ButtonStyle.blurple, custom_id="logrefresh", row=0, emoji=discord.PartialEmoji(name="⏬"))

    async def callback(self, interaction: discord.Interaction):
        global GUI_embed, GUI_view

        file_message = await GUI_data_channel.send(file=discord.File(logFile))
        file_link = file_message.attachments[0].url

        GUI_embed.clear_fields()
        GUI_embed.add_field(name="Log file", value=f"[Download]({file_link})")

        if GUI_view.children[1].label == "Get Download":
            GUI_view.children[1].label = "Refresh Download"
            GUI_view.children[1].emoji = discord.PartialEmoji(name="🔄")

        await update_GUI(interaction)


class logBackButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Back", style=discord.ButtonStyle.blurple, custom_id="logback", row=0, emoji=discord.PartialEmoji(name="⬅️"))

    async def callback(self, interaction: discord.Interaction):
        global GUI_embed, GUI_view, GUI_menu

        GUI_embed.clear_fields()

        GUI_view_log.children[1].label = "Get Download"
        GUI_view_log.children[1].emoji = discord.PartialEmoji(name="⏬")

        GUI_mainmenu()

        GUI_menu = "main"

        await update_GUI(interaction)


class waitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Wait times", style=discord.ButtonStyle.blurple, custom_id="waittimes", row=1, emoji=discord.PartialEmoji(name="⏳"))

    async def callback(self, interaction: discord.Interaction):
        GUI_wait()

        await update_GUI()
        print("Viewed wait times")


class screenButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Screen", style=discord.ButtonStyle.blurple, custom_id="screen", row=1, emoji=discord.PartialEmoji(name="🖥️"))

    async def callback(self, interaction: discord.Interaction):
        global GUI_embed, GUI_view, GUI_menu

        GUI_embed.description = f"Updates every 5 seconds\nIf image doesn't loading, try going to {GUI_data_channel.mention}"

        GUI_view = GUI_view_screen

        GUI_menu = "screen"

        await interaction.response.defer()
        asyncio.create_task(screen_loop())
        print("Viewed screen")


class clearButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Clear data-dump", style=discord.ButtonStyle.red, custom_id="clear", row=2, emoji=discord.PartialEmoji(name="🗑️"))

    async def callback(self, interaction: discord.Interaction):
        global GUI_embed
        GUI_embed.set_footer(text="Clearing data-dump...")
        await interaction.response.defer()
        await update_GUI()

        deleted = await GUI_data_channel.purge(limit=1000, check=lambda m: m.id != GUI_inventoryID)

        if GUI_embed.footer.text == "Clearing data-dump...":
            GUI_embed.set_footer(text=f"Deleted {len(deleted)} messages in data-dump")
            await update_GUI()
        print("Purge data-dump")
        print(f"Deleted {len(deleted)} messages in data-dump")

        await asyncio.sleep(3)
        if GUI_embed.footer.text == f"Deleted {len(deleted)} messages in data-dump":
            GUI_embed.set_footer(text="")
            await update_GUI()


class quitButton(discord.ui.Button):
    def __init__(self, row=2):
        super().__init__(label="Quit", style=discord.ButtonStyle.red, custom_id="quit", row=row, emoji=discord.PartialEmoji(name="⏹️"))

    async def callback(self, interaction: discord.Interaction):
        GUI_quit()

        await update_GUI(interaction)


class quitCancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.blurple, custom_id="quitcancel", row=0, emoji=discord.PartialEmoji(name="❌"))

    async def callback(self, interaction: discord.Interaction):
        global GUI_embed, GUI_view, GUI_menu

        if GUI_menu == "startquit":
            GUI_start()
        elif GUI_menu == "quit":
            GUI_mainmenu()

        await update_GUI(interaction)


class quitConfirmButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Confirm", style=discord.ButtonStyle.red, custom_id="quitconfirm", row=0, emoji=discord.PartialEmoji(name="✅"))

    async def callback(self, interaction: discord.Interaction):
        exit_handler()

        print("Quit bot")
        os._exit(0)


def create_views():
    global GUI_view_start, GUI_view_main, GUI_view_back, GUI_view_log, GUI_view_wait, GUI_view_screen, GUI_view_quit

    GUI_view_start = discord.ui.View(timeout=None)
    GUI_view_start.add_item(startButton())
    GUI_view_start.add_item(quitButton(0))

    GUI_view_main = discord.ui.View(timeout=None)
    GUI_view_main.add_item(pauseButton())
    GUI_view_main.add_item(logButton())
    GUI_view_main.add_item(waitButton())
    GUI_view_main.add_item(screenButton())
    GUI_view_main.add_item(clearButton())
    GUI_view_main.add_item(quitButton())

    GUI_view_back = discord.ui.View(timeout=None)
    GUI_view_back.add_item(backButton())

    GUI_view_log = discord.ui.View(timeout=None)
    GUI_view_log.add_item(logBackButton())
    GUI_view_log.add_item(logDownloadButton())

    GUI_view_wait = discord.ui.View(timeout=None)
    GUI_view_wait.add_item(backButton())

    GUI_view_screen = discord.ui.View(timeout=None)
    GUI_view_screen.add_item(backButton())

    GUI_view_quit = discord.ui.View(timeout=None)
    GUI_view_quit.add_item(quitCancelButton())
    GUI_view_quit.add_item(quitConfirmButton())


@client.event
async def on_ready():
    global ownerID, logFile
    threading.Thread(target=kill).start()
    app_info = await client.application_info()
    ownerID = app_info.owner.id
    i = 0
    while os.path.exists(f"logs/log{i}.txt"):
        i += 1
    logFile = f"logs/log{i}.txt"
    os.makedirs(os.path.dirname(logFile), exist_ok=True)
    open(logFile, "w").close()
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print("Run /start in Discord to start the bot")
    print(f"Press the Del key or use the quit button to stop the script")


async def update_GUI(interaction: discord.Interaction = None):
    global GUI_message
    if GUI_message:
        await GUI_message.edit(embed=GUI_embed, view=GUI_view)
    else:
        GUI_message = await GUI_channel.send(embed=GUI_embed, view=GUI_view)
    if interaction:
        await interaction.response.defer()


@client.tree.command(description="Start the bot")
async def start(interaction: discord.Interaction):
    global roblox, GUI_channel, GUI_guild, GUI_data_channel, GUI_embed, GUI_view, GUI_menu
    if interaction.user.id != ownerID:
        await interaction.response.send_message("Only the owner can use this command", ephemeral=True)
        return

    if GUI_menu != "":
        await interaction.response.send_message("Bot already started", ephemeral=True)
        return

    await interaction.response.send_message("Starting bot...", ephemeral=True)

    # check if tesseract executable exists
    if not os.path.exists(tesseractLocation):
        await interaction.edit_original_response(
            content="Download and install Tesseract from https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.3.0.20221222.exe\n"
            "Then set the path to the executable in `config.py` and run again. Default path is `C:\\Program Files\\Tesseract-OCR\\tesseract.exe`",
            )
        os._exit(0)
    pytesseract.pytesseract.tesseract_cmd = tesseractLocation

    # make sure deliType is either short or long
    if deliType.lower() not in ["short", "long"]:
        await interaction.edit_original_response(content="deliType must be either \"short\" or \"long\"")
        os._exit(0)

    # screen.py auto setup
    if not os.path.exists("screen.py"):
        global template_screen
        await interaction.edit_original_response(content="screen.py not found. Starting setup...")
        await asyncio.sleep(3)
        await interaction.edit_original_response(content="Open inventory and put mouse over the top left slot and press enter when ready\nReference Image: https://cdn.discordapp.com/attachments/792495578486669313/1059785613991231488/image.png")
        keyboard.wait("enter")
        _upperLeft = tuple(pyautogui.position())
        template_screen = template_screen.replace("upperLeftPos", str(_upperLeft))
        await asyncio.sleep(1)
        await interaction.edit_original_response(content="Open inventory and put mouse over the diagonal slot from top left slot and press enter when ready\nReference Image: https://cdn.discordapp.com/attachments/792495578486669313/1059786217933242500/image.png")
        keyboard.wait("enter")
        _difference = tuple(pyautogui.position())
        template_screen = template_screen.replace("differencePos", str((_difference[0] - _upperLeft[0], _difference[1] - _upperLeft[1])))
        await asyncio.sleep(1)
        await interaction.edit_original_response(content="Open inventory and put mouse over top left of item name area and press enter when ready\nReference Image: https://cdn.discordapp.com/attachments/792495578486669313/1059790894783529000/image.png")
        keyboard.wait("enter")
        _nameCord1 = tuple(pyautogui.position())
        template_screen = template_screen.replace("nameCord1Pos", str(_nameCord1))
        await asyncio.sleep(1)
        await interaction.edit_original_response(content="Open inventory and put mouse over bottom right of item name area and press enter when ready\nReference Image: https://cdn.discordapp.com/attachments/792495578486669313/1059791136698400839/image.png")
        keyboard.wait("enter")
        _nameCord2 = tuple(pyautogui.position())
        template_screen = template_screen.replace("nameCord2Pos", str(_nameCord2))
        await asyncio.sleep(1)
        await interaction.edit_original_response(content="Open inventory and put mouse over light purple background behind \"Vanity\" and press enter when ready\nReference Image: https://cdn.discordapp.com/attachments/792495578486669313/1059792527017902200/image.png")
        keyboard.wait("enter")
        _inv = tuple(pyautogui.position())
        _invC = pyautogui.pixel(*_inv)
        template_screen = template_screen.replace("invPos", str(_inv))
        template_screen = template_screen.replace("invC", str(_invC))
        await asyncio.sleep(1)
        await interaction.edit_original_response(content="Sit at the booth and put mouse over white part of \"Ring Bell\" text and press enter when ready\nReference Image: https://cdn.discordapp.com/attachments/792495578486669313/1059795112122646528/image.png")
        keyboard.wait("enter")
        _ring = tuple(pyautogui.position())
        _ringC = pyautogui.pixel(*_ring)
        template_screen = template_screen.replace("ringPos", str(_ring))
        template_screen = template_screen.replace("ringgC", str(_ringC))
        await asyncio.sleep(1)
        await interaction.edit_original_response(content="Click \"Ring Bell\" and put mouse over anywhere near the bottom right green part of dialogue box\nReference Image: https://cdn.discordapp.com/attachments/792495578486669313/1059796493617332284/image.png")
        keyboard.wait("enter")
        _diag = tuple(pyautogui.position())
        _diagC = pyautogui.pixel(*_diag)
        template_screen = template_screen.replace("dialPos", str(_diag))
        template_screen = template_screen.replace("dialC", str(_diagC))
        await asyncio.sleep(1)
        await interaction.edit_original_response(content="Continue dialogue until you get to the two options and put mouse over \"Short wait\" and press enter when ready\nReference Image: https://cdn.discordapp.com/attachments/792495578486669313/1059797532227674162/image.png")
        keyboard.wait("enter")
        _short = tuple(pyautogui.position())
        template_screen = template_screen.replace("shortPos", str(_short))
        await asyncio.sleep(1)
        await interaction.edit_original_response(content="Put mouse over \"Long wait\" and press enter when ready\nReference Image: https://cdn.discordapp.com/attachments/792495578486669313/1059797971887206420/image.png")
        keyboard.wait("enter")
        _long = tuple(pyautogui.position())
        template_screen = template_screen.replace("longPos", str(_long))
        with open("screen.py", "w") as f:
            f.write(template_screen)
        await interaction.edit_original_response(content="screen.py setup complete. Relaunch the bot")
        os._exit(0)

    # populate slotsCord using upperLeft and difference, then extrapolating
    if len(slotsCord) == 0:
        for cordJ in range(4):
            for cordI in range(5):
                slotsCord.append([slotsCordRef["upperLeft"][0] + (slotsCordRef["difference"][0] * cordI),
                                  slotsCordRef["upperLeft"][1] + (slotsCordRef["difference"][1] * cordJ)])

    # get bounding box of inventory
    if inventoryBBox[0][0] == 0:
        inventoryBBox[0][0] = round(slotsCord[0][0] - slotsCordRef["difference"][0] * 0.5)
        inventoryBBox[0][1] = round(slotsCord[0][1] - slotsCordRef["difference"][1] * 0.5)
        inventoryBBox[1][0] = round(slotsCord[19][0] + slotsCordRef["difference"][0] * 0.5)
        inventoryBBox[1][1] = round(slotsCord[19][1] + slotsCordRef["difference"][1] * 0.5)

    GUI_channel = interaction.channel
    GUI_guild = interaction.guild
    bot_user = GUI_guild.get_member(client.user.id)
    permissions = bot_user.guild_permissions
    if not permissions.manage_channels:
        await interaction.edit_original_response(content="Bot does not have permission to manage channels")
        return
    if not permissions.manage_messages:
        await interaction.edit_original_response(content="Bot does not have permission to manage messages")
        return
    if not permissions.read_messages:
        await interaction.edit_original_response(content="Bot does not have permission to read messages")
        return
    if not permissions.read_message_history:
        await interaction.edit_original_response(content="Bot does not have permission to read message history")
        return
    if not permissions.view_channel:
        await interaction.edit_original_response(content="Bot does not have permission to view channel")
        return
    if not permissions.send_messages:
        await interaction.edit_original_response(content="Bot does not have permission to send messages")
        return
    if not permissions.embed_links:
        await interaction.edit_original_response(content="Bot does not have permission to embed links")
        return
    if not permissions.attach_files:
        await interaction.edit_original_response(content="Bot does not have permission to attach files")
        return

    GUI_data_channel = discord.utils.get(client.get_all_channels(), guild__name=GUI_guild.name, name="data-dump")
    if GUI_data_channel is None:
        GUI_data_channel = await GUI_guild.create_text_channel("data-dump")

    # check if roblox is open
    roblox = win32gui.FindWindow(None, "Roblox")
    if roblox == 0:
        await interaction.edit_original_response(content="Waiting for Fantastic Frontier")
        count = 0
        while roblox == 0:
            if count > 36000:
                print("Roblox not found. Exiting")
                os._exit(0)
            roblox = win32gui.FindWindow(None, "Roblox")
            count += 1
            await asyncio.sleep(1)

    await interaction.delete_original_response()
    create_views()

    if forceStart:
        GUI_mainmenu()

        await update_GUI()
        print("Bot force started")
        await main()
        return

    GUI_start()

    await update_GUI()


@client.tree.command(description="Refresh the GUI")
async def refresh(interaction: discord.Interaction):
    if interaction.user.id != ownerID:
        await interaction.response.send_message("Only the owner can use this command", ephemeral=True)
        return
    if GUI_menu == "start" or GUI_menu == "":
        await interaction.response.send_message("Start bot first", ephemeral=True)
        return
    global GUI_message

    await interaction.response.send_message("Refreshing GUI", ephemeral=True)
    await GUI_message.delete()
    GUI_message = None

    GUI_mainmenu()

    await update_GUI()
    await interaction.delete_original_response()


async def screen_loop():
    while GUI_menu == "screen":
        global GUI_embed
        with io.BytesIO() as image_binary:
            ImageGrab.grab().save(image_binary, 'JPEG', quality=50)
            image_binary.seek(0)
            image_message = await GUI_data_channel.send(file=discord.File(fp=image_binary, filename="image.jpg"))
        if GUI_menu != "screen":
            break
        GUI_embed.set_image(url=image_message.attachments[0].url)

        await update_GUI()
        await asyncio.sleep(5)


@client.tree.command(description="See latency of bot")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! {round(client.latency, 2)} sec", ephemeral=True)
    print("Viewed latency")


if __name__ == "__main__":
    if not os.path.exists("config.py"):
        with open("config.py", "w") as f:
            f.write(template_config)
        print("Created config.py")
        print("Please relaunch the script")
        os._exit(0)
    if botToken == "":
        print("You will need to create a bot and set the token in config.py")
        print("1. Go to https://discord.com/developers/applications")
        print("2. Click New Application")
        print("3. Give it a name (ex. DeliBot) and click Create")
        print("4. Click Bot on the left")
        print("5. Click Add Bot")
        print("6. Click Reset Token and copy the token")
        os._exit(0)
    if serverID == 0:
        print("You will need to create a server or use a server you have Manager Server permissions on and set the serverID in config.py")
        print("1. Enable Developer Mode in Discord Settings")
        print("1a. Click User Settings")
        print("1b. Click Advanced")
        print("1c. Enable Developer Mode")
        print("2. Right click on the server and click Copy ID")
        os._exit(0)
    print("Starting Discord bot")
    print("If this takes longer than 5 seconds, stop the script, wait 30 seconds, and restart")
    try:
        atexit.register(exit_handler)
        client.run(botToken,
                   # log_handler=None
                   )
    except discord.Forbidden:
        print("Use this link to invite the bot to your server:")
        print(f"https://discord.com/api/oauth2/authorize?client_id={client.user.id}&permissions=125968&scope=applications.commands%20bot")
        print("Then restart the script")
        os._exit(0)
