import ast
import ctypes
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import time
import webbrowser
import pyautogui
import pyperclip
import requests


# 1. Anti-Debugging Check
def check_debugger():
  try:
    if ctypes.windll.kernel32.IsDebuggerPresent():
      sys.exit(1)
  except Exception:
    pass


check_debugger()


# 2. Extract Device Hardware Fingerprint (Updated for Windows 11 compatibility)
def get_hardware_fingerprint():
  try:
    # Use PowerShell instead of wmic to avoid Windows 11 errors
    cmd = (
        "powershell -Command \"Get-CimInstance Win32_BaseBoard | Select-Object"
        ' -ExpandProperty SerialNumber"'
    )
    result = subprocess.run(
        cmd, capture_output=True, text=True, shell=True, timeout=5
    )
    serial = result.stdout.strip()

    if not serial or "No MSFT" in serial:
      # Second fallback if the motherboard serial is not available
      cmd_fallback = (
          "powershell -Command \"Get-CimInstance Win32_ComputerSystemProduct |"
          ' Select-Object -ExpandProperty IdentifyingNumber"'
      )
      result_fb = subprocess.run(
          cmd_fallback, capture_output=True, text=True, shell=True, timeout=5
      )
      serial = result_fb.stdout.strip()

    if not serial:
      serial = platform.node()

    return hashlib.sha256(serial.encode("utf-8")).hexdigest()
  except Exception:
    return "unknown_device"


# 3. Remote Control URLs (GitHub Raw Links)
REMOTE_ALLOWED_DEVICES_URL = "https://raw.githubusercontent.com/yabd3517-beep/bot-controle/refs/heads/main/allowed_devices.txt"
REMOTE_PASSWORD_URL = "https://raw.githubusercontent.com/yabd3517-beep/bot-controle/refs/heads/main/current_password.txt"


# 4. Auto-update (every device updates itself from GitHub when the bot starts)
APP_VERSION = "1.0.1"
REMOTE_VERSION_URL = "https://raw.githubusercontent.com/yabd3517-beep/bot-controle/refs/heads/main/version.txt"
REMOTE_SCRIPT_URL = "https://raw.githubusercontent.com/yabd3517-beep/bot-controle/refs/heads/main/bot.py"


def parse_version(text):
  try:
    return tuple(int(x) for x in text.strip().split("."))
  except ValueError:
    return None


def sha256_lf(data):
  # line endings are normalised so Windows (CRLF) and GitHub (LF) give the same hash
  return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def fetch_release_info():
  """version.txt: line 1 = version, then optional 'required'/'optional', 'sha256:<hash>', and notes."""
  r = requests.get(REMOTE_VERSION_URL, timeout=8)
  r.raise_for_status()
  lines = [l.strip() for l in r.text.splitlines() if l.strip()]
  info = {"version": lines[0], "required": True, "sha256": None, "notes": []}
  for l in lines[1:]:
    low = l.lower()
    if low in ("required", "optional"):
      info["required"] = low == "required"
    elif low.startswith("sha256:"):
      info["sha256"] = low.split(":", 1)[1].strip()
    else:
      info["notes"].append(l)
  return info


def download_update(info):
  """Downloads the new bot.py and checks it BEFORE anything is replaced."""
  r = requests.get(REMOTE_SCRIPT_URL, timeout=20)
  r.raise_for_status()
  data = r.content
  if len(data) < 1000:
    raise ValueError("the downloaded file is too small")
  if info["sha256"] and sha256_lf(data) != info["sha256"]:
    raise ValueError("the downloaded file does not match its checksum (GitHub may still be updating)")
  code = data.decode("utf-8")
  ast.parse(code)  # must be valid Python
  if f'APP_VERSION = "{info["version"]}"' not in code:
    raise ValueError("the downloaded file has a different version than version.txt")
  return data


def apply_update(data):
  script = os.path.abspath(__file__)
  new_path = script + ".new"
  with open(new_path, "wb") as f:
    f.write(data)
  shutil.copy2(script, script + ".bak")  # the old version is kept as bot.py.bak
  os.replace(new_path, script)


def restart_bot(new_version):
  env = dict(os.environ, BOT_JUST_UPDATED=new_version)
  code = subprocess.call(
      [sys.executable, os.path.abspath(__file__)] + sys.argv[1:], env=env
  )
  sys.exit(code)


def check_for_update():
  if getattr(sys, "frozen", False):
    return  # built as an .exe: self-update is not supported
  try:
    info = fetch_release_info()
  except Exception as e:
    print(f"(Could not check for updates: {e})")
    return

  remote, local = parse_version(info["version"]), parse_version(APP_VERSION)
  if remote is None or local is None or remote <= local:
    return

  print("\n==============================================")
  print(f" Update available: {APP_VERSION} -> {info['version']}")
  for note in info["notes"]:
    print(f"   {note}")
  print("==============================================")
  if info["required"]:
    input("This update is required. Press Enter to update now... ")
  elif input("Update now? (y/n): ").strip().lower() != "y":
    return

  try:
    data = download_update(info)
    apply_update(data)
  except Exception as e:
    print(f"Update failed: {e}\nNothing was changed.")
    if info["required"]:
      print("This update is required. Please try again in a few minutes.")
      sys.exit(1)
    return

  print("Update installed. Restarting the bot...\n")
  restart_bot(info["version"])


def verify_device():
  current_device_id = get_hardware_fingerprint()
  print(f"Device Fingerprint: {current_device_id}")

  try:
    # Check the allowed devices list on GitHub
    response_devices = requests.get(REMOTE_ALLOWED_DEVICES_URL, timeout=5)
    allowed_devices = response_devices.text.splitlines()

    if current_device_id not in allowed_devices:
      print(
          "Access Denied: This device is not authorized or access has been"
          " revoked."
      )
      sys.exit(1)

    print("Device Authorized.")
  except Exception as e:
    print(f"Security Error: Unable to verify status online. ({e})")
    sys.exit(1)


def verify_password():
  try:
    # Check the cloud password on GitHub
    response_password = requests.get(REMOTE_PASSWORD_URL, timeout=5)
    correct_password = response_password.text.strip()

    # Ask the user for the password at startup
    entered_password = input("Enter password to run the bot: ").strip()

    if entered_password == correct_password:
      print("Password Correct! Access Granted.\n")
    else:
      print("Access Denied: Incorrect password!")
      sys.exit(1)
  except Exception as e:
    print(f"Security Error: Unable to verify status online. ({e})")
    sys.exit(1)


def send_to_multiple_links(links_list, text_message):
  pyperclip.copy(text_message)
  print(f"Starting to send the message to {len(links_list)} links...\n")

  for index, url in enumerate(links_list, 1):
    print(f"[{index}/{len(links_list)}] Opening link: {url}")

    try:
      webbrowser.open(url)
      print("Waiting 9 seconds for page to load...")
      time.sleep(9)

      pyautogui.hotkey("ctrl", "v")
      time.sleep(0.8)
      pyautogui.press("enter")

      print(f"Successfully sent to link {index}!\n")
    except pyautogui.FailSafeException:
      print("Stopped: the mouse was moved to a screen corner.")
      raise
    except Exception as e:
      print(f"-> Error encountered: {e}. Skipping and continuing...")

    time.sleep(4)


if __name__ == "__main__":
  # 1) device check, 2) update check (restarts the bot if it updates), 3) password.
  # The update comes before the password so you only type the password once.
  print(f"Bot version {APP_VERSION}")
  if os.environ.get("BOT_JUST_UPDATED"):
    print(f"(Updated to version {os.environ['BOT_JUST_UPDATED']})")
  verify_device()
  check_for_update()
  verify_password()

  # Message 1 (With Discord Link)
  msg_with_link = """# ╭ ⬥ —・〘4501〙・— ⬥ ╮
# │⚜ Empire Of Legends ⚜│
# ╰ ⬥ —・ ⬥—⬥ —・ ⬥  ╯
## __🏛️ About Us__
> **Members Count**: 80+
> **Date**: January 2028
> **Kingdom**: 4501

## __🎯 Goals__
**Members**
> -# -Reach for 4,000 Members in discord
> -# -Build the largest and most active project ever recorded

**Spenders**
> -# -Spreading Spender
> -# -10 T5 by KvK 1
> -# -8 T4 by day 1

**Alliances**
> -# -2 Main, 4 Subs
> -# -Dominate leaderboard
> -# -Fully organized by day 1

## __📜 Information__
**Experience**
> -# Filled with former kings and multiple experience leadership from Imperium, Seed A and etc

**High Spender**
> -# A lot of Mid Spender, Whales and possible Kraken in contact

## __🔎 Looking For__
**Spenders**
> -# We looking for High Spenders who willing to help us spreading gc to all members equally

**Experience**
> -# We need an experience players to help us reach our biggest goal and winning each KvKs with our kingdom name

**Active**
> -# We are searching for any actives F2P player to maintain our kingdom activities even in its down time

## __📞 Contact Founders__
<@1089136290475282502> 
<@1395921768941879409> 
**Discord Link**: https://discord.gg/empireoflegends
**[Image](https://cdn.discordapp.com/attachments/1564305127517458576/1566155336203899051/1000014816.png?ex=6ae78351&is=6ae631d1&hm=1a0a45dee5307a663ca8224d131b42f4cad340fe270204eef3f7971b6106a2bd&)**"""

  # Message 2 (Without Direct Link / Code Only)
  msg_without_link = """# ╭ ⬥ —・〘4501〙・— ⬥ ╮
# │⚜ Empire Of Legends ⚜│
# ╰ ⬥ —・ ⬥—⬥ —・ ⬥  ╯
## __🏛️ About Us__
> **Members Count**: 80+
> **Date**: January 2028
> **Kingdom**: 4501

## __🎯 Goals__
**Members**
> -# -Reach for 4,000 Members in discord
> -# -Build the largest and most active project ever recorded

**Spenders**
> -# -Spreading Spender
> -# -10 T5 by KvK 1
> -# -8 T4 by day 1

## __Alliances__
> -# -2 Main, 4 Subs
> -# -Dominate leaderboard
> -# -Fully organized by day 1

## __📜 Information__
**Experience**
> -# Filled with former kings and multiple experience leadership from Imperium, Seed A and etc

**High Spender**
> -# A lot of Mid Spender, Whales and possible Kraken in contact

## __🔎 Looking For__
**Spenders**
> -# We looking for High Spenders who willing to help us spreading gc to all members equally

**Experience**
> -# We need an experience players to help us reach our biggest goal and winning each KvKs with our kingdom name

**Active**
> -# We are searching for any actives F2P player to maintain our kingdom activities even in its down time

## __📞 Contact Founders__
<@1089136290475282502>  
<@1395921768941879409> 
**Discord Code**: ``empireoflegends``
**[Image](https://cdn.discordapp.com/attachments/1564305127517458576/1566155336203899051/1000014816.png?ex=6ae78351&is=6ae631d1&hm=1a0a45dee5307a663ca8224d131b42f4cad340fe270204eef3f7971b6106a2bd&)**"""

  campaigns = [
      {
          "name": "with links",
          "message": msg_with_link,
          "links": [
              "https://discord.com/channels/861710119762395176/1011299373575057528",
              "https://discord.com/channels/911120169248653312/1285916839305678952",
              "https://discord.com/channels/999977616801009764/1073573575912607766",
              "https://discord.com/channels/506780419539337227/583038988823035914",
              "https://discord.com/channels/709116787446513706/826784069387157504",
              "https://discord.com/channels/1042352643881828412/1129498358499774596",
              "https://discord.com/channels/701438618937458769/702171020366446622",
              "https://discord.com/channels/1025587845261430896/1162072743827746846",
              "https://discord.com/channels/420678591181881346/1056996713098924053",
              "https://discord.com/channels/1163108113101111388/1203454743096332358",
              "https://discord.com/channels/919284187536699542/1409937586298028043",
              "https://discord.com/channels/779279997189881856/879622934157746197",
              "https://discord.com/channels/1213498927068745809/1240749315815903284",
              "https://discord.com/channels/990726194079100988/1067434589863297075",
              "https://discord.com/channels/1200962975100588132/1250210841941508097",
              "https://discord.com/channels/1200962975100588132/1250210702069727232",
              "https://discord.com/channels/690287049999122683/772827289071124501",
              "https://discord.com/channels/660754609974804481/857609766480904232",
              "https://discord.com/channels/660754609974804481/857614733208059915",
              "https://discord.com/channels/1351231060918272020/1351231061551743140",
              "https://discord.com/channels/1037084156653486150/1242265450591817738",
              "https://discord.com/channels/1037084156653486150/1037089675560636477",
              "https://discord.com/channels/506780419539337227/567451034964721675",
              "https://discord.com/channels/506780419539337227/564925400216633344",
              "https://discord.com/channels/506780419539337227/525996826575503360",
              "https://discord.com/channels/506780419539337227/526095127534501912",
              "https://discord.com/channels/506780419539337227/765614860620791849",
              "https://discord.com/channels/506780419539337227/630890065928781874",
              "https://discord.com/channels/506780419539337227/780545702383845407",
              "https://discord.com/channels/999977616801009764/1073573639804432414",
              "https://discord.com/channels/420678591181881346/1056996472719155250",
              "https://discord.com/channels/1081025409950437497/1125209828650909756",
              "https://discord.com/channels/772081926978797570/830050112855736330",
              "https://discord.com/channels/772081926978797570/830050485515845632",
              "https://discord.com/channels/772081926978797570/830050642483347498",
              "https://discord.com/channels/660754609974804481/1091364889492205598",
              "https://discord.com/channels/660754609974804481/872902306063065160",
              "https://discord.com/channels/990714059634663424/1011341182929993859",
              "https://discord.com/channels/779279997189881856/879623055230500914",
              "https://discord.com/channels/1213498927068745809/1240748870909300756",
              "https://discord.com/channels/1093098282286325800/1093112158188998696",
              "https://discord.com/channels/1093098282286325800/1093110626768924692",
              "https://discord.com/channels/1093098282286325800/1093112245577322568",
              "https://discord.com/channels/1093098282286325800/1093110532107669554",
              "https://discord.com/channels/1176738901310836756/1497296017723359392",
              "https://discord.com/channels/744727496590622910/744997234114035832",
              "https://discord.com/channels/744727496590622910/744997282537275422",
              "https://discord.com/channels/1405630397701951648/1559525003479879730",
              "https://discord.com/channels/1200962975100588132/1250210771519143979",
              "https://discord.com/channels/1125530340266610708/1411025753180606554",
              "https://discord.com/channels/1125530340266610708/1411025681936023707",
              "https://discord.com/channels/709116787446513706/709116788188905484",
              "https://discord.com/channels/709116787446513706/846739377400053760",
              "https://discord.com/channels/876024433733664789/915706292063076372",
              "https://discord.com/channels/876024433733664789/1157041947282767952",
              "https://discord.com/channels/876024433733664789/915610616704663584",
          ],
      },
      {
          "name": "without links",
          "message": msg_without_link,
          "links": [
              "https://discord.com/channels/538735518037442560/561191347034521646",
              "https://discord.com/channels/605225953614102549/705205838171603058",
              "https://discord.com/channels/1275762835821166754/1275862562235486240",
              "https://discord.com/channels/1275762835821166754/1275862773670088754",
              "https://discord.com/channels/1219665653330608149/1255329480407519333",
              "https://discord.com/channels/901459729686069259/903187069034192916",
              "https://discord.com/channels/921139008581566505/921457566498832405",
              "https://discord.com/channels/641739778290745356/714087042203648000",
          ],
      },
  ]

  for i, campaign in enumerate(campaigns, 1):
    print(
        f"\n===== {campaign['name']} ({i}/{len(campaigns)}) - Total Links:"
        f" {len(campaign['links'])} ====="
    )
    if len(campaign["links"]) > 0:
      send_to_multiple_links(campaign["links"], campaign["message"])
    else:
      print("No links provided in this campaign. Skipping...")
    print("Waiting 10 seconds before next campaign...")
    time.sleep(10)

  print("\nAll campaigns finished successfully!")