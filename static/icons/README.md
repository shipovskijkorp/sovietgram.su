# Telegram Desktop icon source

The files under `static/icons/telegram-original/` are copied byte-for-byte
from the Telegram Desktop 7.2.9 source archive supplied for this project.
They are not redrawn, traced, rescaled, or converted into custom SVG paths.

Telegram stores many menu icons as grayscale raster masks. Stalingram renders
those original PNG files with CSS `mask-mode: luminance`, which preserves the
original Telegram geometry and antialiasing while applying Stalingram's own
interface colors.

The older `telegram.svg` sprite is retained only for controls that have not
yet been migrated to the original raster assets.

Telegram Desktop is distributed under the GNU General Public License version 3
with its documented OpenSSL exception. See the upstream Telegram Desktop
repository and license for the applicable terms.
