# Market Tracker

A simple market and shopping list tracker. Add items with a quantity, price and discount, and the total is worked out for you. It comes in two versions that share the same design: a **Python desktop app** and a **mobile-friendly web page**.

The look is a crumpled off-white paper with dark brown text in the [Doto](https://fonts.google.com/specimen/Doto) font. Prices are in rupees (₹).

## Try it on your phone

Scan the QR code to open the web version:

<p align="center">
  <img width="410" height="410" alt="QR-031026-19-13" src="https://github.com/user-attachments/assets/8c7c04ea-d4bb-4ba3-9dd2-6cc69a017255" />
</p>

Or open it directly: **https://superguine.github.io/Market_Tracker/**

## Features

- Add, edit and delete items with a name, details, quantity, unit and unit price
- Item discounts (percentage or a fixed ₹ amount) and a discount on the whole bill
- Live subtotal, savings and final total, with Indian digit grouping (₹1,00,000.00)
- Tick items off as bought
- Undo after deleting an item or clearing the list
- Input checks: no empty names, zero quantities, negative prices, or discounts larger than the item
- Your list is saved automatically

## How the total is worked out

1. Line total = quantity × unit price
2. Item discount = a percentage or fixed amount, never more than the line total
3. Subtotal = the sum of all line totals after item discounts
4. Bill discount = a percentage or fixed amount, never more than the subtotal
5. **Total = subtotal − bill discount**

## Python desktop app

**Requirements:** Python 3 with Tkinter. There are no other dependencies.

```bash
python3 market_tracker.py
```

If Tkinter is missing, the script tries to install it with your system package manager (`dnf`, `apt` or `pacman`). You can also install it yourself. On Fedora:

```bash
sudo dnf install python3-tkinter
```

Your list is saved to `~/.market_tracker.json`.

### Using the Doto font (optional)

Tkinter can only use fonts installed on your system. If Doto isn't found, the app falls back to a monospace font.

1. Download Doto from [Google Fonts](https://fonts.google.com/specimen/Doto).
2. Copy the `.ttf` files to your fonts folder and refresh the cache:

```bash
mkdir -p ~/.local/share/fonts
cp Doto-*.ttf ~/.local/share/fonts/
fc-cache -f
```

3. Restart the app.

## Web version

Open `market-tracker.html` in any browser. It's a single file with no build step and no install. The Doto font loads from Google Fonts, so you need an internet connection the first time.

The web version is laid out for phones too: larger touch targets, and a bar at the bottom of the screen that always shows the total. Its list is stored in the browser (localStorage).

## Notes

- The desktop app, the web page on your phone, and the web page on your computer each keep their own separate list. They don't sync with each other.
- Clearing your browser data removes the web list.

## Project structure

```
Market_Tracker/
├── market_tracker.py      # Python (Tkinter) desktop app
├── market-tracker.html    # Web version (HTML, CSS and JavaScript in one file)
├── assets/
│   └── qr-code.png        # QR code for the web page
└── README.md
```
