# Compose fixtures

Synthetic, written by hand after the Compose specification and compose-go's loader.

- `compose.yaml`: a web, db and worker service with an interpolated project name, short and long port syntax,
  bind mounts (relative, read-only, absolute), named and external volumes, a container name from an unset
  variable and an invalid port entry.
- `compose.override.yaml`: the override file Compose merges automatically; it renames the web container and adds
  a port.
