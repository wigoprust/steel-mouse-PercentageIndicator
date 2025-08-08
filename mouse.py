# Import the essential modules
import rivalcfg, pystray, os, time, threading
from PIL import Image, ImageDraw

# --- Numeric tray icon renderer (Pillow) ---
from PIL import Image, ImageDraw, ImageFont

def render_battery_icon(percent: int, charging: bool) -> Image.Image:
    # Size: 24x24 works well on Win11; system will scale as needed
    size = 24
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Colors by threshold (your request): green >50, yellow 25–50, red <25
    if percent > 50:
        fill = (70, 190, 80, 255)
    elif percent >= 25:
        fill = (240, 180, 50, 255)
    else:
        fill = (230, 80, 70, 255)

    outline = (235, 235, 235, 255)
    white = (255, 255, 255, 255)
    shadow = (0, 0, 0, 160)

    # Battery body
    pad = 2
    body = [pad, pad, size - (pad*2), size - (pad*2)]
    d.rounded_rectangle(body, radius=4, outline=outline, width=2)

    # Nub
    nub_w = 4
    nub_h = size // 3
    nub_x = body[2] + 1
    nub_y = body[1] + ((body[3]-body[1]) - nub_h) // 2
    d.rectangle([nub_x, nub_y, nub_x + nub_w, nub_y + nub_h], fill=outline)

    # Fill level
    inner_pad = 4
    inner = [body[0] + inner_pad, body[1] + inner_pad, body[2] - inner_pad, body[3] - inner_pad]
    inner_w = inner[2] - inner[0]
    fill_w = max(0, int(inner_w * max(0, min(100, percent)) / 100))
    d.rectangle([inner[0], inner[1], inner[0] + fill_w, inner[3]], fill=fill)

    # Optional lightning bolt when charging
    if charging and percent < 100:
        cx = (inner[0] + inner[2]) // 2
        cy = (inner[1] + inner[3]) // 2
        w = max(4, (inner[2]-inner[0]) // 3)
        h = max(6, (inner[3]-inner[1]) // 2)
        pts = [
            (cx - w//3, cy - h//2), (cx, cy - h//2),
            (cx - w//6, cy), (cx + w//3, cy),
            (cx - w//6, cy + h//2), (cx - w//2, cy + h//2),
            (cx, cy), (cx - w//3, cy - h//2)
        ]
        d.polygon(pts, fill=(245, 245, 245, 255))

    # Percentage text “00”
    txt = f"{int(percent):02d}"
    # Try a readable Windows font; fall back to default
    try:
        font = ImageFont.truetype("segoeuib.ttf", 17)  # Segoe UI Semibold if available
    except Exception:
        font = ImageFont.load_default()

    tw, th = d.textbbox((0, 0), txt, font=font)[2:]
    tx = body[0] + ((body[2] - body[0]) - tw) / 2
    ty = body[1] + ((body[3] - body[1]) - th) / 2

    # Shadow for contrast
    d.text((tx+0.5, ty+0.5), txt, font=font, fill=shadow)
    d.text((tx, ty), txt, font=font, fill=white)

    return img

# Our state variables
last_update = None
battery_level = None
battery_charging = None
icon = None
stopped = False
event = None

# Change the default in the `time_delta.txt` file to change the update interval
time_delta_default = 60 * 5  # Default to 5 minutes if file is empty
time_error_retry = 1 / 20  # Retry every 1/20 seconds if an error occurs
time_delta = time_delta_default
time_deltas = [60, 300, 600, 1800, 3600]  # 1min, 5min, 10min, 30min, 1h
time_error = 60 * 0.2  # 60s * 0.2 = 12s

directory = f"{os.path.dirname(os.path.realpath(__file__))}/"
image_directory = f"{directory}images/"


# Function to load the time delta from a file
def load_time_delta():
    global time_delta
    try:
        with open(f"{directory}time_delta.txt", "r") as f:
            content = f.read().strip()
            if content and content.isdigit():
                time_delta = int(content)
            else:
                time_delta = time_delta_default
            print(f"Time delta loaded: {time_delta} seconds")
    except FileNotFoundError:
        print("No time_delta.txt found, using default value.")
        time_delta = time_delta_default



# Fuction to create the menu
def create_menu(name, battery_level, last_update, battery_charging):
    return pystray.Menu(
        pystray.MenuItem(
            f"Name: {name}",
            lambda: None,
            radio=False,
        ),
        pystray.MenuItem(
            f"Battery: {str(f'{battery_level}%' if battery_level is not None else 'N/A')}",
            lambda: None,
        ),
        pystray.MenuItem(
            (
                "Status: Charging"
                if battery_charging else "Status: Discharging"
            ),
            lambda: None,
        ),
        pystray.MenuItem(
            text="Last updated at: "
            + time.strftime("%H:%M:%S", time.localtime(last_update))
            + f" (Interval: {time_delta if battery_level is not None else time_error_retry}s)",
            action=pystray.Menu(
                *[
                    pystray.MenuItem(
                        text=f"{int(t / 60)} minute{'s' if t != 60 else ''}",
                        action=set_time_delta,
                        checked=lambda t=t: t == time_delta,
                        default=(
                            t == time_delta
                        ),
                        radio=True,
                    )
                    for t in time_deltas
                ],
            ),
        ),
        pystray.MenuItem("Quit", quit_app),
    )


# Function to load the images
def load_image(image_name):
    return Image.open(f"{image_directory}{image_name}.png")


# Function to get the battery data
def get_battery(event: threading.Event):
    global stopped, icon, battery_level, last_update, battery_charging
    mouse = None
    while not stopped:
        try:
            mouse = rivalcfg.get_first_mouse()
            print(f"Mouse found {mouse}")
            if mouse is None:
                print("No mouse found")
                time.sleep(time_error_retry)
                raise Exception

            battery = mouse.battery
            battery = mouse.battery

            print(f"Mouse battery {battery}")

            if battery is not None:
                name = mouse.name
                if battery["level"] is not None:
                    battery_level = max(min(battery["level"], 100), 0)
                    last_update = time.time()
                    battery_charging = battery["is_charging"]
                if icon is not None:
                    icon.icon = create_battery_icon()
                    icon.menu = create_menu(
                        name, battery_level, last_update, battery_charging
                    )
                    icon.title = f"Battery: {str(f'{battery_level}%' if battery_level is not None else 'N/A')}"
                    icon.update_menu()
                load_time_delta()
                sleeptime = time_delta if battery["level"] is not None else time_error_retry
                event.clear()
                event.wait(timeout=sleeptime)
            else:
                print("No battery found")
                time.sleep(time_error_retry)
        except Exception as e:
            print(f"Error: {e}\n\nSleeping for {time_error} seconds...")
            time.sleep(time_error)
    
    if mouse is not None:
        mouse.close()
    print("Stopping thread")

def create_battery_icon():
    # Use the new numeric battery icon renderer
    global battery_level, battery_charging
    level = 0 if battery_level is None else int(battery_level)
    charging = bool(battery_charging) if battery_charging is not None else False
    return render_battery_icon(level, charging)


# Function to refresh the connection
# Legacy used to force an update
def refresh_connection():
    global event
    if event is None:
        print("Event is None, cannot refresh connection.")
        return
    event.set()


# This function is called when you click to change the time delta
def set_time_delta(icon, item):
    global event
    if event is None:
        print("Event is None, cannot set time delta.")
        return
    global time_delta
    new_time_delta = int(item.text.split(" ")[0]) * 60
    print(f"Setting time delta to {new_time_delta} seconds.")
    time_delta = new_time_delta
    print(f"Time delta set to {time_delta} seconds.")
    # save the value to a file or config if needed
    with open(f"{directory}time_delta.txt", "w+") as f:
        f.write(str(time_delta))
    event.set()


# This function is called when you click on the quit button
def quit_app(icon, item):
    global stopped
    icon.stop()
    stopped = True


# This is the main function, where we initialize the system tray icon and start the thread
def main():
    global icon
    global event

    event = threading.Event()
    image = create_battery_icon()
    icon = pystray.Icon("Battery", icon=image, title="Battery: N/A")
    thread = threading.Thread(target=get_battery, args=(event,))
    thread.daemon = True
    thread.start()
    icon.menu = pystray.Menu(
        pystray.MenuItem(
            "Looking for mouse and mouse data...",
            lambda: None,
        ),
        pystray.MenuItem("Quit", quit_app),
    )
    icon.run()


# Python boilerplate
if __name__ == "__main__":
    main()
