//! `PyO3` module entry point. Registers v2 (legacy) and v3 (seek-table + integrity) pack/unpack
//! functions exposed to Python as `native_woof_impl`.

pub mod entry;
pub mod error;
pub mod pack;
pub mod seek_table;
pub mod unpack;

use pyo3::prelude::*;

/// Register all Python-callable functions on the `native_woof_impl` module.
#[pymodule]
fn native_woof_impl(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(pack::pack_v2_py, m)?)?;
    m.add_function(wrap_pyfunction!(unpack::unpack_v2_py, m)?)?;
    m.add_function(wrap_pyfunction!(pack::pack_v3_py, m)?)?;
    m.add_function(wrap_pyfunction!(unpack::unpack_v3_py, m)?)?;
    m.add_function(wrap_pyfunction!(unpack::unpack_one_py, m)?)?;
    m.add_function(wrap_pyfunction!(unpack::list_entries_py, m)?)?;
    Ok(())
}
