{
  lib,
  python3Packages,
  openssh,
  git,
}:

let
  versionLine = lib.findFirst (lib.hasPrefix "__version__ = ") null (
    lib.splitString "\n" (builtins.readFile ./src/freepod/__init__.py)
  );
in
python3Packages.buildPythonApplication {
  pname = "freepod";
  version = lib.removeSuffix "\"" (lib.removePrefix "__version__ = \"" versionLine);
  pyproject = true;

  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      ./src
      ./tests
      ./pyproject.toml
      ./README.md
      ./LICENSE
    ];
  };

  build-system = [ python3Packages.hatchling ];

  dependencies = with python3Packages; [
    click
    httpx
    pathspec
    prompt-toolkit
  ];

  makeWrapperArgs = [
    "--suffix"
    "PATH"
    ":"
    (lib.makeBinPath [
      openssh
      git
    ])
  ];

  nativeCheckInputs = [
    python3Packages.pytestCheckHook
    openssh
    git
  ];

  pythonImportsCheck = [ "freepod" ];

  meta = {
    description = "Command-line client for Freepod";
    homepage = "https://freepod.eu";
    license = lib.licenses.mit;
    mainProgram = "freepod";
  };
}
