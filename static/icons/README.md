# Telegram Desktop icon source

The files under `static/icons/telegram-original/` are copied byte-for-byte
from the Telegram Desktop 7.2.9 source archive supplied for this project.

Stalingram does not redraw or trace these icons. Telegram Desktop ships many
interface icons as opaque grayscale raster masks; Stalingram uses those same
PNG files as CSS luminance masks. This preserves Telegram's original geometry,
optical bounds and antialiasing while letting the interface apply the
Stalingram palette.

The previous handcrafted `telegram.svg` sprite was removed after the original
assets were integrated.

Telegram Desktop is distributed under the GNU General Public License version 3
with its documented OpenSSL exception. See the upstream Telegram Desktop
repository and license for the applicable terms.
