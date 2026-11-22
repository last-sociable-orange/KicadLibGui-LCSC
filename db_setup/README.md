# KiCad database-library setup

Two ready-made `.kicad_dbl` files map the `components` table to KiCad's symbol
chooser:

| File | Use on |
|---|---|
| `components_db_windows.kicad_dbl` | Windows, `Driver={SQLite3 ODBC Driver}` |
| `components_db_linux.kicad_dbl` | Linux, `Driver={SQLite3}` |

They describe the same library; only the ODBC connection string differs. Both list
all 80 columns in table order, and `tests/test_dbl_files.py` fails if the mapping
and `kicad_core.models.ALL_COLUMNS` ever drift apart.

## Before you use them

1. **Install an SQLite ODBC driver.**
   - Windows: [sqliteodbc](http://www.ch-werner.de/sqliteodbc/) (`sqlite3odbc.dll`),
     registered as `SQLite3 ODBC Driver`.
   - Linux: `apt install libsqliteodbc` (driver name `SQLite3`).
2. **Point the connection string at your database.** The defaults expect the
   program's suggested location:

   | Platform | Connection string |
   |---|---|
   | Windows | `Driver={SQLite3 ODBC Driver};Database=${USERPROFILE}\KiCadLibGenLCSC\components.db` |
   | Linux | `Driver={SQLite3};Database=${HOME}/KiCadLibGenLCSC/components.db` |

   KiCad expands `${USERPROFILE}` / `${HOME}` from the environment. If your database
   lives somewhere else — or your KiCad build does not expand the variable — replace
   the whole value with an absolute path:

   ```
   Driver={SQLite3 ODBC Driver};Database=D:\KiCad\components.db
   ```

3. **Register the file in KiCad:** *Preferences → Manage Symbol Libraries →*
   *Database* tab → **Add** → browse to the `.kicad_dbl` file. The library nickname
   becomes `components`, so symbols are referenced as `components:<symbol>`.

The `KicadSymbolLibrary` / `KicadFootprintLibrary` columns contain what you typed in
the program (`Symbol:?` is expanded to `Symbol:<MPN>` on save), so those must name
libraries that exist in your KiCad installation.

## What the columns mean

| Column | Content for LCSC parts |
|---|---|
| `ID` | `<category>/<MPN>`, also the library key |
| `Description` | the store's product name / intro |
| `Keywords` | longer introduction, remark |
| `Value` | the value parameter when there is one (`10kΩ` → `10K`), else the MPN |
| `Manufacturer` | brand, e.g. `UNI-ROYAL(厚声)` |
| `ManufacturerProductNumber` | MPN, e.g. `0603WAF1002T5E` |
| `Package` | `0603`, `LQFP-48(7x7)` |
| `PartStatus` | `Active`, `Obsolete`, `Pre-order`, … |
| `QtyAvailable` | the stock the store showed when the part was saved |
| `Distributor` | `LCSC` (szlcsc.com) or `LCSC International` (lcsc.com) |
| `DistributorProductNumber` | the LCSC part number, e.g. `C25804` |
| `UnitPrice` | `¥0.0101@1/¥0.0079@10/…`, or `US$…` in English mode |
| `ProductUrl` | the storefront product page |
| `DatasheetUrl` | the datasheet the store links to |
| `Param01..32` / `Value01..32` | the parameter name / value pairs, headline specs first |

## Field names

Every `name` equals its `column`. In KiCad the field name is also the symbol field
it populates, so this keeps the mapping obvious and keeps symbols from an older
database library working. If you prefer shorter names in the chooser (for example
`MPN` instead of `ManufacturerProductNumber`), change **both** the `name` here and
the field name on your symbols — otherwise the value will not transfer.

`Value` is the only field with `"visible_on_add": true`; that is the value a symbol
gets when you place it from the chooser. `Keywords` is the only column hidden from
the chooser.

## Regenerating

The files are generated from the schema so they cannot fall behind it:

```bash
python tools/gen_dbl.py          # rewrites both files from ALL_COLUMNS
pytest tests/test_dbl_files.py   # proves the mapping still matches the table
```
