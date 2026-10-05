//! A tiny library.
use std::fmt;

/// Max items.
pub const MAX: usize = 4;
static mut COUNTER: u32 = 0;

#[derive(Debug, Clone)]
pub struct Point<'a> {
    pub x: i32,
    label: &'a str,
}

pub struct Unit;

pub enum Shape {
    Circle { r: f64 },
    #[allow(dead_code)]
    Square(f64),
    Empty,
}

pub trait Area {
    fn area(&self) -> f64;
    fn name(&self) -> String {
        String::from("shape")
    }
}

impl<'a> Point<'a> {
    pub fn new(x: i32, label: &'a str) -> Self {
        let s = r#"raw "{" string"#;
        let c = '}';
        Point { x, label }
    }

    fn private_helper(&self) {}
}

impl fmt::Display for Point<'_> {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "({})", self.x)
    }
}

pub mod inner {
    pub fn helper() {}
}

mod tests;

macro_rules! square {
    ($x:expr) => { $x * $x };
}

pub(crate) fn crate_fn<'a, T: Clone>(v: &'a T) -> T where T: Copy {
    v.clone()
}

extern "C" {
    fn abs(x: i32) -> i32;
}
