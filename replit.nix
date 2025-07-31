{ pkgs }: {
  deps = [
    # Existing Python environment
    pkgs.nano
    pkgs.python311
    pkgs.python311Packages.pip
    pkgs.python311Packages.setuptools
    pkgs.python311Packages.wheel
    pkgs.python311Packages.requests
    pkgs.python311Packages.stem

    # Added for JS/Zip extraction
    pkgs.unzip
    pkgs.nodejs
    pkgs.nodePackages.npm
  ];
}

