pub mod entry;
pub mod error;
pub mod pack;
pub mod seek_table;
pub mod unpack;

use pyo3::prelude::*;

#[pymodule]
fn native_woof_impl(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // v2 compat
    m.add_function(wrap_pyfunction!(pack::pack_v2_py, m)?)?;
    m.add_function(wrap_pyfunction!(unpack::unpack_v2_py, m)?)?;

    // v3 new
    m.add_function(wrap_pyfunction!(pack::pack_v3_py, m)?)?;
    m.add_function(wrap_pyfunction!(unpack::unpack_v3_py, m)?)?;
    m.add_function(wrap_pyfunction!(unpack::unpack_one_py, m)?)?;
    m.add_function(wrap_pyfunction!(unpack::list_entries_py, m)?)?;

    Ok(())
}
