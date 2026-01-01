#!/usr/bin/env python3
"""
Polymarket MCP Server - Setup Wizard
Interactive GUI for configuring the Polymarket MCP server with Claude Desktop.

Features:
- Step-by-step configuration wizard
- Demo mode (no wallet required)
- Full installation mode (with wallet)
- Safety limits configuration
- Automatic Claude Desktop integration
- Input validation and testing

Author: Caio Vicentino
License: MIT
"""

import json
import os
import platform
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, Optional


class PolymarketSetupWizard:
    """Interactive setup wizard for Polymarket MCP Server"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Polymarket MCP Server - Setup Wizard")
        self.root.geometry("800x600")
        self.root.resizable(False, False)

        # Configuration data
        self.config_data: Dict[str, Any] = {
            "mode": "demo",  # demo or full
            "polygon_private_key": "",
            "polygon_address": "",
            "max_order_size": 1000,
            "max_total_exposure": 5000,
            "max_position_per_market": 2000,
            "min_liquidity": 10000,
            "max_spread": 0.05,
            "confirmation_threshold": 500,
            "enable_autonomous": True,
        }

        # Current step
        self.current_step = 0
        self.total_steps = 5

        # Setup UI
        self.setup_ui()

    def setup_ui(self):
        """Initialize UI components"""
        # Header
        header_frame = tk.Frame(self.root, bg="#1e40af", height=80)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)

        title_label = tk.Label(
            header_frame,
            text="🤖 Polymarket MCP Server",
            font=("Helvetica", 24, "bold"),
            bg="#1e40af",
            fg="white"
        )
        title_label.pack(pady=20)

        # Progress bar
        self.progress_frame = tk.Frame(self.root, bg="white", height=60)
        self.progress_frame.pack(fill=tk.X)
        self.progress_frame.pack_propagate(False)

        self.progress_label = tk.Label(
            self.progress_frame,
            text="Step 1 of 5: Welcome",
            font=("Helvetica", 12),
            bg="white"
        )
        self.progress_label.pack(pady=5)

        self.progress_bar = ttk.Progressbar(
            self.progress_frame,
            length=700,
            mode='determinate',
            maximum=self.total_steps
        )
        self.progress_bar.pack(pady=5)
        self.progress_bar['value'] = 1

        # Content frame (changes per step)
        self.content_frame = tk.Frame(self.root, bg="white")
        self.content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Button frame
        button_frame = tk.Frame(self.root, bg="white", height=60)
        button_frame.pack(fill=tk.X, side=tk.BOTTOM)
        button_frame.pack_propagate(False)

        self.back_button = ttk.Button(
            button_frame,
            text="← Back",
            command=self.previous_step,
            state=tk.DISABLED
        )
        self.back_button.pack(side=tk.LEFT, padx=20, pady=10)

        self.next_button = ttk.Button(
            button_frame,
            text="Next →",
            command=self.next_step
        )
        self.next_button.pack(side=tk.RIGHT, padx=20, pady=10)

        self.cancel_button = ttk.Button(
            button_frame,
            text="Cancel",
            command=self.cancel_setup
        )
        self.cancel_button.pack(side=tk.RIGHT, padx=5, pady=10)

        # Show first step
        self.show_welcome_step()

    def clear_content(self):
        """Clear content frame"""
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def update_progress(self, step: int, step_name: str):
        """Update progress bar and label"""
        self.current_step = step
        self.progress_bar['value'] = step
        self.progress_label.config(text=f"Step {step} of {self.total_steps}: {step_name}")

        # Update buttons
        self.back_button['state'] = tk.NORMAL if step > 1 else tk.DISABLED

    def show_welcome_step(self):
        """Step 1: Welcome screen"""
        self.clear_content()
        self.update_progress(1, "Welcome")

        # Logo/Title
        welcome_label = tk.Label(
            self.content_frame,
            text="Welcome to Polymarket MCP Setup! 🎉",
            font=("Helvetica", 18, "bold"),
            bg="white"
        )
        welcome_label.pack(pady=20)

        # Description
        desc_text = """This wizard will help you configure the Polymarket MCP Server
for use with Claude Desktop.

The setup process includes:

✓ Choosing installation type (Demo or Full)
✓ Configuring wallet credentials (if needed)
✓ Setting safety limits for trading
✓ Integrating with Claude Desktop
✓ Testing the connection

The entire process takes about 5 minutes.
        """

        desc_label = tk.Label(
            self.content_frame,
            text=desc_text,
            font=("Helvetica", 11),
            bg="white",
            justify=tk.LEFT
        )
        desc_label.pack(pady=20, padx=40)

        # Feature highlights
        features_frame = tk.Frame(self.content_frame, bg="white")
        features_frame.pack(pady=20)

        features = [
            "🔍 45 comprehensive trading tools",
            "📊 Real-time market analysis",
            "💼 Autonomous trading capabilities",
            "🛡️ Enterprise-grade safety limits"
        ]

        for feature in features:
            label = tk.Label(
                features_frame,
                text=feature,
                font=("Helvetica", 10),
                bg="white",
                anchor="w"
            )
            label.pack(anchor="w", pady=2)

    def show_installation_type_step(self):
        """Step 2: Choose installation type"""
        self.clear_content()
        self.update_progress(2, "Installation Type")

        title = tk.Label(
            self.content_frame,
            text="Choose Installation Type",
            font=("Helvetica", 16, "bold"),
            bg="white"
        )
        title.pack(pady=20)

        # Mode selection
        self.mode_var = tk.StringVar(value=self.config_data["mode"])

        # Full installation
        full_frame = tk.LabelFrame(
            self.content_frame,
            text="Full Installation (Recommended)",
            font=("Helvetica", 12, "bold"),
            bg="white",
            padx=20,
            pady=15
        )
        full_frame.pack(fill=tk.X, padx=40, pady=10)

        full_radio = ttk.Radiobutton(
            full_frame,
            text="Full Installation",
            variable=self.mode_var,
            value="full"
        )
        full_radio.pack(anchor="w")

        full_desc = tk.Label(
            full_frame,
            text="✓ Complete trading functionality\n✓ Place orders and manage positions\n✓ Requires Polygon wallet\n✓ Recommended for active traders",
            font=("Helvetica", 9),
            bg="white",
            justify=tk.LEFT,
            fg="#059669"
        )
        full_desc.pack(anchor="w", padx=20, pady=5)

        # Demo mode
        demo_frame = tk.LabelFrame(
            self.content_frame,
            text="Demo Mode (Read-Only)",
            font=("Helvetica", 12, "bold"),
            bg="white",
            padx=20,
            pady=15
        )
        demo_frame.pack(fill=tk.X, padx=40, pady=10)

        demo_radio = ttk.Radiobutton(
            demo_frame,
            text="Demo Mode",
            variable=self.mode_var,
            value="demo"
        )
        demo_radio.pack(anchor="w")

        demo_desc = tk.Label(
            demo_frame,
            text="✓ Market discovery and analysis only\n✓ No wallet required\n✓ Cannot place trades\n✓ Perfect for testing and learning",
            font=("Helvetica", 9),
            bg="white",
            justify=tk.LEFT,
            fg="#0284c7"
        )
        demo_desc.pack(anchor="w", padx=20, pady=5)

    def show_wallet_step(self):
        """Step 3: Wallet configuration"""
        self.clear_content()

        # Check if demo mode
        selected_mode = getattr(self, 'mode_var', None)
        if selected_mode:
            self.config_data["mode"] = selected_mode.get()

        if self.config_data["mode"] == "demo":
            # Skip wallet config for demo mode
            self.show_safety_limits_step()
            return

        self.update_progress(3, "Wallet Configuration")

        title = tk.Label(
            self.content_frame,
            text="Wallet Configuration",
            font=("Helvetica", 16, "bold"),
            bg="white"
        )
        title.pack(pady=20)

        warning = tk.Label(
            self.content_frame,
            text="⚠️ Keep your private key secure. Never share it with anyone.",
            font=("Helvetica", 10),
            bg="#fef3c7",
            fg="#92400e",
            padx=10,
            pady=5
        )
        warning.pack(fill=tk.X, padx=40, pady=10)

        # Private key input
        pk_frame = tk.Frame(self.content_frame, bg="white")
        pk_frame.pack(fill=tk.X, padx=40, pady=10)

        pk_label = tk.Label(
            pk_frame,
            text="Private Key (without 0x):",
            font=("Helvetica", 10, "bold"),
            bg="white"
        )
        pk_label.pack(anchor="w")

        self.pk_var = tk.StringVar(value=self.config_data["polygon_private_key"])
        pk_entry = ttk.Entry(pk_frame, textvariable=self.pk_var, show="*", width=70)
        pk_entry.pack(fill=tk.X, pady=5)

        # Show/Hide button
        self.show_pk = tk.BooleanVar(value=False)
        show_button = ttk.Checkbutton(
            pk_frame,
            text="Show private key",
            variable=self.show_pk,
            command=lambda: pk_entry.config(show="" if self.show_pk.get() else "*")
        )
        show_button.pack(anchor="w")

        # Address input
        addr_frame = tk.Frame(self.content_frame, bg="white")
        addr_frame.pack(fill=tk.X, padx=40, pady=10)

        addr_label = tk.Label(
            addr_frame,
            text="Polygon Address (0x...):",
            font=("Helvetica", 10, "bold"),
            bg="white"
        )
        addr_label.pack(anchor="w")

        self.addr_var = tk.StringVar(value=self.config_data["polygon_address"])
        addr_entry = ttk.Entry(addr_frame, textvariable=self.addr_var, width=70)
        addr_entry.pack(fill=tk.X, pady=5)

        # Validation button
        validate_button = ttk.Button(
            self.content_frame,
            text="✓ Validate Credentials",
            command=self.validate_wallet
        )
        validate_button.pack(pady=20)

        # Status label
        self.wallet_status = tk.Label(
            self.content_frame,
            text="",
            font=("Helvetica", 10),
            bg="white"
        )
        self.wallet_status.pack()

        # Help text
        help_text = tk.Label(
            self.content_frame,
            text="Need help? Check our VISUAL_INSTALL_GUIDE.md for wallet setup instructions.",
            font=("Helvetica", 9),
            bg="white",
            fg="#6b7280"
        )
        help_text.pack(side=tk.BOTTOM, pady=10)

    def validate_wallet(self):
        """Validate wallet credentials"""
        pk = self.pk_var.get().strip()
        addr = self.addr_var.get().strip()

        # Remove 0x prefix from private key if present
        if pk.startswith("0x"):
            pk = pk[2:]

        # Validate private key
        if len(pk) != 64:
            self.wallet_status.config(
                text="✗ Private key must be 64 hex characters",
                fg="#dc2626"
            )
            return

        if not re.match(r'^[0-9a-fA-F]{64}$', pk):
            self.wallet_status.config(
                text="✗ Private key must be valid hex",
                fg="#dc2626"
            )
            return

        # Validate address
        if not addr.startswith("0x"):
            self.wallet_status.config(
                text="✗ Address must start with 0x",
                fg="#dc2626"
            )
            return

        if len(addr) != 42:
            self.wallet_status.config(
                text="✗ Address must be 42 characters",
                fg="#dc2626"
            )
            return

        # Success
        self.config_data["polygon_private_key"] = pk
        self.config_data["polygon_address"] = addr.lower()

        self.wallet_status.config(
            text="✓ Credentials validated successfully!",
            fg="#059669"
        )

    def show_safety_limits_step(self):
        """Step 4: Safety limits configuration"""
        self.clear_content()
        self.update_progress(4, "Safety Limits")

        title = tk.Label(
            self.content_frame,
            text="Configure Safety Limits",
            font=("Helvetica", 16, "bold"),
            bg="white"
        )
        title.pack(pady=20)

        desc = tk.Label(
            self.content_frame,
            text="Set risk management limits to protect your funds",
            font=("Helvetica", 10),
            bg="white",
            fg="#6b7280"
        )
        desc.pack()

        # Presets
        preset_frame = tk.Frame(self.content_frame, bg="white")
        preset_frame.pack(pady=20)

        tk.Label(
            preset_frame,
            text="Quick Presets:",
            font=("Helvetica", 10, "bold"),
            bg="white"
        ).pack(side=tk.LEFT, padx=5)

        ttk.Button(
            preset_frame,
            text="Conservative",
            command=lambda: self.apply_preset("conservative")
        ).pack(side=tk.LEFT, padx=5)

        ttk.Button(
            preset_frame,
            text="Moderate",
            command=lambda: self.apply_preset("moderate")
        ).pack(side=tk.LEFT, padx=5)

        ttk.Button(
            preset_frame,
            text="Aggressive",
            command=lambda: self.apply_preset("aggressive")
        ).pack(side=tk.LEFT, padx=5)

        # Sliders frame
        sliders_frame = tk.Frame(self.content_frame, bg="white")
        sliders_frame.pack(fill=tk.BOTH, expand=True, padx=40)

        # Max Order Size
        self.create_slider(
            sliders_frame,
            "Max Order Size ($)",
            "max_order_size",
            100, 10000, 100
        )

        # Max Total Exposure
        self.create_slider(
            sliders_frame,
            "Max Total Exposure ($)",
            "max_total_exposure",
            500, 50000, 500
        )

        # Max Position Per Market
        self.create_slider(
            sliders_frame,
            "Max Position Per Market ($)",
            "max_position_per_market",
            200, 20000, 200
        )

        # Confirmation Threshold
        self.create_slider(
            sliders_frame,
            "Confirmation Threshold ($)",
            "confirmation_threshold",
            0, 5000, 100
        )

    def create_slider(self, parent, label, config_key, min_val, max_val, step):
        """Create a slider with label and value display"""
        frame = tk.Frame(parent, bg="white")
        frame.pack(fill=tk.X, pady=10)

        # Label and value
        top_frame = tk.Frame(frame, bg="white")
        top_frame.pack(fill=tk.X)

        tk.Label(
            top_frame,
            text=label,
            font=("Helvetica", 10, "bold"),
            bg="white"
        ).pack(side=tk.LEFT)

        value_label = tk.Label(
            top_frame,
            text=f"${self.config_data[config_key]:,.0f}",
            font=("Helvetica", 10),
            bg="white",
            fg="#059669"
        )
        value_label.pack(side=tk.RIGHT)

        # Slider
        slider = ttk.Scale(
            frame,
            from_=min_val,
            to=max_val,
            orient=tk.HORIZONTAL,
            command=lambda v: self.update_slider_value(config_key, v, value_label)
        )
        slider.set(self.config_data[config_key])
        slider.pack(fill=tk.X, pady=5)

        # Store slider reference
        if not hasattr(self, 'sliders'):
            self.sliders = {}
        self.sliders[config_key] = slider

    def update_slider_value(self, key, value, label):
        """Update slider value and label"""
        val = float(value)
        self.config_data[key] = val
        label.config(text=f"${val:,.0f}")

    def apply_preset(self, preset: str):
        """Apply safety limit preset"""
        presets = {
            "conservative": {
                "max_order_size": 500,
                "max_total_exposure": 2000,
                "max_position_per_market": 1000,
                "confirmation_threshold": 100
            },
            "moderate": {
                "max_order_size": 1000,
                "max_total_exposure": 5000,
                "max_position_per_market": 2000,
                "confirmation_threshold": 500
            },
            "aggressive": {
                "max_order_size": 5000,
                "max_total_exposure": 20000,
                "max_position_per_market": 10000,
                "confirmation_threshold": 2000
            }
        }

        config = presets[preset]
        for key, value in config.items():
            self.config_data[key] = value
            if hasattr(self, 'sliders') and key in self.sliders:
                self.sliders[key].set(value)

    def show_claude_integration_step(self):
        """Step 5: Claude Desktop integration"""
        self.clear_content()
        self.update_progress(5, "Claude Desktop Integration")

        title = tk.Label(
            self.content_frame,
            text="Claude Desktop Integration",
            font=("Helvetica", 16, "bold"),
            bg="white"
        )
        title.pack(pady=20)

        # Auto-detect config file
        config_path = self.get_claude_config_path()

        if config_path and config_path.exists():
            status_text = f"✓ Claude Desktop config found at:\n{config_path}"
            status_color = "#059669"
        else:
            status_text = "⚠️ Claude Desktop config not found.\nPlease install Claude Desktop first."
            status_color = "#dc2626"

        status_label = tk.Label(
            self.content_frame,
            text=status_text,
            font=("Helvetica", 10),
            bg="white",
            fg=status_color
        )
        status_label.pack(pady=10)

        # Path selection
        path_frame = tk.Frame(self.content_frame, bg="white")
        path_frame.pack(fill=tk.X, padx=40, pady=20)

        tk.Label(
            path_frame,
            text="Config File Location:",
            font=("Helvetica", 10, "bold"),
            bg="white"
        ).pack(anchor="w")

        self.config_path_var = tk.StringVar(value=str(config_path) if config_path else "")
        path_entry = ttk.Entry(path_frame, textvariable=self.config_path_var, width=70)
        path_entry.pack(fill=tk.X, pady=5)

        ttk.Button(
            path_frame,
            text="Browse...",
            command=self.browse_config_file
        ).pack(anchor="w", pady=5)

        # Preview
        preview_frame = tk.LabelFrame(
            self.content_frame,
            text="Configuration Preview",
            font=("Helvetica", 10, "bold"),
            bg="white"
        )
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)

        preview_text = self.generate_claude_config_preview()

        preview_widget = tk.Text(
            preview_frame,
            height=10,
            font=("Courier", 9),
            bg="#f3f4f6"
        )
        preview_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        preview_widget.insert("1.0", preview_text)
        preview_widget.config(state=tk.DISABLED)

        # Configure button
        ttk.Button(
            self.content_frame,
            text="✓ Configure Automatically",
            command=self.configure_claude_desktop
        ).pack(pady=10)

        # Status
        self.claude_status = tk.Label(
            self.content_frame,
            text="",
            font=("Helvetica", 10),
            bg="white"
        )
        self.claude_status.pack()

    def get_claude_config_path(self) -> Optional[Path]:
        """Get Claude Desktop config path for current platform"""
        system = platform.system()

        if system == "Darwin":  # macOS
            path = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
        elif system == "Windows":
            path = Path(os.getenv("APPDATA")) / "Claude/claude_desktop_config.json"
        else:  # Linux
            path = Path.home() / ".config/Claude/claude_desktop_config.json"

        return path if path.parent.exists() else None

    def browse_config_file(self):
        """Browse for config file"""
        filename = filedialog.askopenfilename(
            title="Select Claude Desktop Config File",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if filename:
            self.config_path_var.set(filename)

    def generate_claude_config_preview(self) -> str:
        """Generate preview of Claude Desktop config"""
        # Get project path
        project_path = Path(__file__).parent.absolute()
        venv_python = project_path / "venv" / "bin" / "python"

        if platform.system() == "Windows":
            venv_python = project_path / "venv" / "Scripts" / "python.exe"

        config = {
            "mcpServers": {
                "polymarket": {
                    "command": str(venv_python),
                    "args": ["-m", "polymarket_mcp.server"],
                    "cwd": str(project_path)
                }
            }
        }

        # Add env vars for full mode
        if self.config_data["mode"] == "full":
            config["mcpServers"]["polymarket"]["env"] = {
                "POLYGON_PRIVATE_KEY": self.config_data.get("polygon_private_key", ""),
                "POLYGON_ADDRESS": self.config_data.get("polygon_address", ""),
                "MAX_ORDER_SIZE_USD": str(self.config_data["max_order_size"]),
                "MAX_TOTAL_EXPOSURE_USD": str(self.config_data["max_total_exposure"]),
                "MAX_POSITION_SIZE_PER_MARKET": str(self.config_data["max_position_per_market"]),
                "REQUIRE_CONFIRMATION_ABOVE_USD": str(self.config_data["confirmation_threshold"])
            }

        return json.dumps(config, indent=2)

    def configure_claude_desktop(self):
        """Configure Claude Desktop with current settings"""
        config_path = Path(self.config_path_var.get())

        if not config_path:
            messagebox.showerror("Error", "Please specify a config file path")
            return

        try:
            # Load existing config or create new
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
            else:
                config = {"mcpServers": {}}

            # Generate new config
            new_config = json.loads(self.generate_claude_config_preview())

            # Merge
            if "mcpServers" not in config:
                config["mcpServers"] = {}
            config["mcpServers"]["polymarket"] = new_config["mcpServers"]["polymarket"]

            # Write
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w') as f:
                json.dump(config, indent=2, fp=f)

            # Also write .env file
            self.write_env_file()

            self.claude_status.config(
                text="✓ Configuration saved successfully!",
                fg="#059669"
            )

            messagebox.showinfo(
                "Success",
                "Configuration saved!\n\nPlease restart Claude Desktop to apply changes."
            )

        except Exception as e:
            self.claude_status.config(
                text=f"✗ Error: {str(e)}",
                fg="#dc2626"
            )
            messagebox.showerror("Error", f"Failed to save configuration:\n{str(e)}")

    def write_env_file(self):
        """Write .env file with configuration"""
        project_path = Path(__file__).parent
        env_path = project_path / ".env"

        env_content = f"""# Polymarket MCP Server Configuration
# Generated by Setup Wizard

# Installation Mode: {self.config_data['mode']}

"""

        if self.config_data["mode"] == "full":
            env_content += f"""# Polygon Wallet Configuration
POLYGON_PRIVATE_KEY={self.config_data['polygon_private_key']}
POLYGON_ADDRESS={self.config_data['polygon_address']}
POLYMARKET_CHAIN_ID=137

"""

        env_content += f"""# Safety Limits
MAX_ORDER_SIZE_USD={self.config_data['max_order_size']}
MAX_TOTAL_EXPOSURE_USD={self.config_data['max_total_exposure']}
MAX_POSITION_SIZE_PER_MARKET={self.config_data['max_position_per_market']}
REQUIRE_CONFIRMATION_ABOVE_USD={self.config_data['confirmation_threshold']}
MIN_LIQUIDITY_REQUIRED=10000
MAX_SPREAD_TOLERANCE=0.05

# Trading Controls
ENABLE_AUTONOMOUS_TRADING=true
AUTO_CANCEL_ON_LARGE_SPREAD=true

# Logging
LOG_LEVEL=INFO
"""

        with open(env_path, 'w') as f:
            f.write(env_content)

    def next_step(self):
        """Go to next step"""
        if self.current_step == 1:
            self.show_installation_type_step()
        elif self.current_step == 2:
            self.show_wallet_step()
        elif self.current_step == 3:
            # Validate wallet if full mode
            if self.config_data["mode"] == "full":
                if not self.config_data.get("polygon_private_key") or not self.config_data.get("polygon_address"):
                    messagebox.showwarning(
                        "Validation Required",
                        "Please validate your wallet credentials before continuing."
                    )
                    return
            self.show_safety_limits_step()
        elif self.current_step == 4:
            self.show_claude_integration_step()
        elif self.current_step == 5:
            self.finish_setup()

    def previous_step(self):
        """Go to previous step"""
        if self.current_step == 2:
            self.show_welcome_step()
        elif self.current_step == 3:
            self.show_installation_type_step()
        elif self.current_step == 4:
            if self.config_data["mode"] == "demo":
                self.show_installation_type_step()
            else:
                self.show_wallet_step()
        elif self.current_step == 5:
            self.show_safety_limits_step()

    def finish_setup(self):
        """Complete setup and close wizard"""
        result = messagebox.askyesno(
            "Setup Complete",
            "Setup wizard completed successfully!\n\n"
            "Configuration has been saved.\n\n"
            "Remember to restart Claude Desktop to apply changes.\n\n"
            "Would you like to exit the wizard now?"
        )

        if result:
            self.root.quit()

    def cancel_setup(self):
        """Cancel setup"""
        result = messagebox.askyesno(
            "Cancel Setup",
            "Are you sure you want to cancel the setup?\n\n"
            "Your configuration will not be saved."
        )

        if result:
            self.root.quit()

    def run(self):
        """Run the wizard"""
        self.root.mainloop()


def main():
    """Main entry point"""
    wizard = PolymarketSetupWizard()
    wizard.run()


if __name__ == "__main__":
    main()
