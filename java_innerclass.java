class java_innerclass {

    void show() {
              
        System.out.println("Inner class data: ");
    }

    static class InnerClass {
        static void display() {
            System.out.println("Static Inner class method called.");
        }
    }
    public static void main(String[] args) {
        java_innerclass.InnerClass outer = new java_innerclass.InnerClass();
        //java_innerclass  out = new java_innerclass();
        //InnerClass outer = out.new InnerClass();
        //InnerClass.java_innerclass outer = new InnerClass(). new java_innerclass();
        outer.display();
        InnerClass anon= new InnerClass(){
           void display() {
                System.out.println("2222Anonymous Inner class method called.");
        }};
        InnerClass.display();
    
    }
}