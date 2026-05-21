pub mod entry;
pub mod pack;
pub mod unpack;

use pyo3::prelude::*;

#[pymodule]
fn _native_impl(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(pack::pack_v2_py, m)?)?;
    m.add_function(wrap_pyfunction!(unpack::unpack_v2_py, m)?)?;
    Ok(())
}
