{
  description = "freepod, the command-line client for Freepod";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      forAllSystems = nixpkgs.lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
    in
    {
      packages = forAllSystems (system: rec {
        freepod = nixpkgs.legacyPackages.${system}.callPackage ./cli/package.nix { };
        default = freepod;
      });

      checks = self.packages;
    };
}
